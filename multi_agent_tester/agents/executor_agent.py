"""Executor Agent — run pytest, analyze failures, apply bounded self-healing."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import AgentLLMConfig
from ..state import ExecutionReport, FailureFix, SessionState
from ..tools.code_analysis_tools import read_file  # reused for inspecting page objects
from ..tools.execution_tools import EXECUTION_TOOLS
from ..tools.playwright_tools import PlaywrightToolbox
from .base_agent import BaseAgent


SYSTEM = """You are a test-runner and auto-repair agent for a Playwright POM suite.

You have tools: run_pytest, parse_test_failures, classify_failure, replace_in_file,
write_execution_report, read_file, launch_browser, navigate_to, current_url,
get_interactive_elements, relocate_element, capture_screenshot, close_browser.

Process:

1. run_pytest once on the automation_dir to get the baseline results.
2. For each failed test, read the corresponding page object and classify_failure.
3. Self-heal ONLY 'selector' and 'timing' categories:
   - For 'selector': launch_browser, navigate to the page URL, use relocate_element
     to find the new locator, then replace_in_file in the page-object file.
     Use the OLD locator_expression exactly as it appears in the file as old_snippet.
   - For 'timing': add `self.page.wait_for_load_state("networkidle")` before the action
     via replace_in_file.
   After each fix, re-run that specific test (pytest test_path=file::name) and stop
   retrying at 3 attempts per test.
4. Anything 'assertion' or 'app_bug' is listed as unresolved — DO NOT alter product code.
5. Finally, write_execution_report with the full summary.

Return ONLY the final JSON summary (no prose):
{
  "total": n, "passed": n, "failed": n, "fixed": n, "skipped": n,
  "fixes_applied": [{"test_name":..., "root_cause":..., "file_changed":..., "diff":...}],
  "unresolved_failures": [{"name":..., "error_message":...}]
}
"""


class ExecutorAgent(BaseAgent):
    name = "executor"
    system_prompt = SYSTEM

    def __init__(self, llm_cfg: AgentLLMConfig, toolbox: PlaywrightToolbox, verbose: bool = False):
        self.toolbox = toolbox
        tools = EXECUTION_TOOLS + [read_file] + toolbox.as_tools()
        super().__init__(llm_cfg, tools, verbose=verbose)

    def execute(self, state: SessionState) -> ExecutionReport:
        if not state.artifacts.automation_dir:
            raise ValueError("Executor needs artifacts.automation_dir to run against")

        instruction = (
            f"automation_dir = {state.artifacts.automation_dir}\n"
            f"app_url = {state.user_input.app_url}\n"
            f"browser = {state.user_input.browser}  headless = {state.user_input.headless}\n"
            f"max_self_heal_retries = {state.user_input.max_self_heal_retries}\n"
            f"workers = {state.user_input.test_parallel_workers}\n\n"
            "Execute the process. Return ONLY the JSON summary."
        )
        raw = self.run(instruction)

        try:
            self.toolbox.close()
        except Exception:  # noqa: BLE001
            pass

        data = _coerce_json(raw)
        return ExecutionReport(
            total=int(data.get("total", 0)),
            passed=int(data.get("passed", 0)),
            failed=int(data.get("failed", 0)),
            fixed=int(data.get("fixed", 0)),
            skipped=int(data.get("skipped", 0)),
            fixes_applied=[FailureFix(**f) for f in data.get("fixes_applied", []) if f.get("test_name")],
            unresolved_failures=list(data.get("unresolved_failures", [])),
            report_path=state.artifacts.automation_dir / "test_results" / "execution_report.html"
            if state.artifacts.automation_dir else None,
        )


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
