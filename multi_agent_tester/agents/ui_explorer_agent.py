"""UI Explorer Agent — drives a live Playwright browser to map the UI."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import AgentLLMConfig
from ..state import AppAnalysis, PageElement, PageMap, SessionState, UIMap, Workflow
from ..tools.playwright_tools import PlaywrightToolbox
from .base_agent import BaseAgent


SYSTEM = """You drive a live Playwright browser to discover the structure of a running web app.

You have tools: launch_browser, navigate_to, current_url, get_page_structure,
get_interactive_elements, click_element, fill_form, smart_fill_form,
wait_for_navigation, capture_screenshot, relocate_element, close_browser.

Workflow:
1. launch_browser(url, browser, headless).
2. For EACH workflow in the Analyst's plan, navigate the UI end-to-end (login first if auth is required).
3. On each page you land on, call get_interactive_elements and remember the results keyed by page name.
4. For forms, prefer smart_fill_form over manual fills when credentials are not provided.
5. capture_screenshot after major state changes (post-login, cart, checkout).
6. close_browser when finished.

Return ONLY a JSON object (no prose):
{
  "pages": {
    "<page_name>": {
      "url": "...",
      "title": "...",
      "elements": {
        "<element_name>": {
          "selector": "<raw_selector>",
          "locator_strategy": "data-test|role|label|placeholder|id|text|css",
          "type": "button|input|link|...",
          "description": "short"
        }
      }
    }
  },
  "workflows": [
    {
      "name": "...",
      "description": "...",
      "pages_involved": ["login", "dashboard"],
      "steps": ["navigate /login", "fill username", "click submit", "assert url /dashboard"]
    }
  ]
}
"""


class UIExplorerAgent(BaseAgent):
    name = "ui_explorer"
    system_prompt = SYSTEM

    def __init__(self, llm_cfg: AgentLLMConfig, toolbox: PlaywrightToolbox, verbose: bool = False):
        self.toolbox = toolbox
        super().__init__(llm_cfg, toolbox.as_tools(), verbose=verbose)

    def explore(self, state: SessionState, analysis: AppAnalysis) -> UIMap:
        creds = state.user_input.credentials
        workflows_hint = json.dumps([w.model_dump() for w in analysis.workflows], indent=2)
        instruction = (
            f"Target URL: {state.user_input.app_url}\n"
            f"Browser: {state.user_input.browser}  Headless: {state.user_input.headless}\n"
            f"Known routes: {analysis.routes}\n"
            f"Auth-required routes: {analysis.auth_required_routes}\n"
            f"Credentials available: {list(creds.keys())} (values not shown — use them only to log in)\n"
            f"Candidate workflows to validate:\n{workflows_hint}\n\n"
            f"Drive the UI. Return ONLY the JSON object specified."
        )
        # Inject credentials into the instruction without exposing values in logs
        if creds:
            instruction += (
                f"\n\nCREDENTIALS (for login only): username={creds.get('username','')} "
                f"password={creds.get('password','')}"
            )

        raw = self.run(instruction)
        # Always close the browser, even if JSON parse fails
        try:
            self.toolbox.close()
        except Exception:  # noqa: BLE001
            pass

        data = _coerce_json(raw)
        ui = UIMap()
        for name, page in (data.get("pages") or {}).items():
            elements: dict[str, PageElement] = {}
            for el_name, el in (page.get("elements") or {}).items():
                elements[el_name] = PageElement(
                    name=el_name,
                    selector=el.get("selector", ""),
                    locator_strategy=el.get("locator_strategy", "css"),
                    type=el.get("type", "element"),
                    description=el.get("description", ""),
                )
            ui.pages[name] = PageMap(
                name=name,
                url=page.get("url", ""),
                title=page.get("title", ""),
                elements=elements,
            )
        for w in data.get("workflows", []):
            if w.get("name"):
                ui.workflows.append(Workflow(**w))
        return ui


def _coerce_json(text: str) -> dict:
    if not text:
        return {}
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}
