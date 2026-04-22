"""Code Generator Agent — produces manual cases + Playwright POM automation."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import AgentLLMConfig
from ..state import AppAnalysis, GeneratedArtifacts, SessionState, UIMap
from ..tools.codegen_tools import CODEGEN_TOOLS
from .base_agent import BaseAgent


SYSTEM = """You generate high-quality QA artifacts for a web application.

You have tools: generate_project_scaffold, generate_page_object, generate_test_file,
generate_manual_tests, validate_python_syntax.

Process (follow strictly — do NOT invent extra tools):

1. Call generate_project_scaffold ONCE to create base_page.py, conftest.py, pytest.ini, utils/.
2. For each page in the UI map, call generate_page_object with a JSON array of the page's elements.
   Each element must include: name, locator_expression, strategy, type, tag, description.
   The locator_expression MUST be a self.page.* expression (e.g.
   'self.page.get_by_test_id("login-button")') — the template rewrites `page.` → `self.page.`,
   so you may pass `page.get_by_test_id(...)` and it will still work.
3. For each workflow in the UI map, call generate_test_file. Steps are a JSON array of
   {action, target, value?, page_attr, description}. Valid actions: navigate, fill, click,
   assert_url, assert_visible, assert_text, wait.
   `page_attr` is the local variable name you gave the page object in `imports`.
4. Generate a rich MANUAL TEST SUITE via generate_manual_tests. Include positive,
   negative, boundary, and security cases. Each case needs:
   {id, title, priority, type, preconditions, steps[], expected}.
   Cover every workflow with at least one happy-path + one negative case.
5. For every test file you wrote, call validate_python_syntax. If any fail, regenerate them.

Return a concise JSON summary ONLY:
{
  "manual_tests_path": "...",
  "automation_dir": "...",
  "page_objects": ["path", ...],
  "test_files": ["path", ...]
}
"""


class CodeGeneratorAgent(BaseAgent):
    name = "codegen"
    system_prompt = SYSTEM

    def __init__(self, llm_cfg: AgentLLMConfig, verbose: bool = False):
        super().__init__(llm_cfg, CODEGEN_TOOLS, verbose=verbose)

    def generate(self, state: SessionState, analysis: AppAnalysis, ui_map: UIMap) -> GeneratedArtifacts:
        instruction = (
            f"output_dir = {state.output_dir}\n"
            f"base_url = {state.user_input.app_url}\n"
            f"credentials_json = {json.dumps(state.user_input.credentials)}\n\n"
            f"APP ANALYSIS:\n{analysis.model_dump_json(indent=2)}\n\n"
            f"UI MAP (ground truth for selectors):\n{ui_map.model_dump_json(indent=2)}\n\n"
            "Execute the 5-step process. Return ONLY the JSON summary."
        )
        raw = self.run(instruction)
        data = _coerce_json(raw)
        return GeneratedArtifacts(
            manual_tests_path=_p(data.get("manual_tests_path")),
            automation_dir=_p(data.get("automation_dir")),
            page_objects=list(data.get("page_objects", [])),
            test_files=list(data.get("test_files", [])),
        )


def _p(v) -> Path | None:
    return Path(v) if v else None


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
