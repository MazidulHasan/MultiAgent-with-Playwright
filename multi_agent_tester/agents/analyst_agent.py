"""Analyst Agent — static repo + docs analysis."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import AgentLLMConfig
from ..state import AppAnalysis, SessionState, Workflow
from ..tools.code_analysis_tools import CODE_ANALYSIS_TOOLS
from .base_agent import BaseAgent


SYSTEM = """You are a senior backend / full-stack engineer doing static analysis of a web application.

GOAL: Produce a structured understanding of the app so a QA team can write regression tests.

You have tools to: list_directory, read_file, search_code, detect_repo_framework,
extract_app_routes, extract_app_entities, parse_documentation.

Workflow:
1. detect_repo_framework on the repo path.
2. list_directory and read_file on README / package.json / config to get oriented.
3. extract_app_routes and extract_app_entities for grounded facts.
4. If a user-guide path is provided, parse_documentation on it.
5. Synthesize 5-15 USER WORKFLOWS that QA must regress (login, key CRUD, checkout, etc).

When you are done, RETURN ONLY a JSON object (no prose) of shape:
{
  "framework": "...",
  "routes": ["/", "/login", ...],
  "auth_required_routes": ["/dashboard", ...],
  "auth_mechanism": "session|jwt|oauth|unknown",
  "entities": ["User", "Order", ...],
  "workflows": [
    {"name": "...", "description": "...", "steps": ["...", "..."], "pages_involved": ["login", "dashboard"]}
  ],
  "notes": ["..."]
}
"""


class AnalystAgent(BaseAgent):
    name = "analyst"
    system_prompt = SYSTEM

    def __init__(self, llm_cfg: AgentLLMConfig, verbose: bool = False):
        super().__init__(llm_cfg, CODE_ANALYSIS_TOOLS, verbose=verbose)

    def analyze(self, state: SessionState, user_guide_path: Path | None = None) -> AppAnalysis:
        instruction = (
            f"Analyze the web application at repo_path='{state.user_input.repo_path}'.\n"
            f"App URL: {state.user_input.app_url}\n"
        )
        if user_guide_path and user_guide_path.exists():
            instruction += f"User guide / docs: {user_guide_path}\n"
        instruction += "Use the tools to gather facts. Return ONLY the JSON object described in your instructions."

        raw = self.run(instruction)
        data = _coerce_json(raw)
        analysis = AppAnalysis(
            framework=data.get("framework", "unknown"),
            routes=list(data.get("routes", [])),
            auth_required_routes=list(data.get("auth_required_routes", [])),
            auth_mechanism=data.get("auth_mechanism", "unknown"),
            entities=list(data.get("entities", [])),
            workflows=[Workflow(**w) for w in data.get("workflows", []) if w.get("name")],
            notes=list(data.get("notes", [])),
        )
        return analysis


def _coerce_json(text: str) -> dict:
    """Pull a JSON object out of the LLM's response, tolerant of code fences or prose."""
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
