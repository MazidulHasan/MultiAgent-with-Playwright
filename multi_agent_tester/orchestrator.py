"""Orchestrator — coordinates the 4 specialized agents and owns SessionState."""
from __future__ import annotations

from pathlib import Path

from .agents import AnalystAgent, CodeGeneratorAgent, ExecutorAgent, UIExplorerAgent
from .config import settings
from .state import SessionState, UserInput
from .tools.playwright_tools import PlaywrightToolbox
from .utils.logger import configure as configure_logger, get_logger, log_event


class Orchestrator:
    def __init__(self, user_input: UserInput, verbose: bool = False):
        self.user_input = user_input
        self.verbose = verbose

        run_dir = settings.output_dir / "runs"
        run_dir.mkdir(parents=True, exist_ok=True)
        self.state = SessionState(
            output_dir=run_dir,
            user_input=user_input,
        )
        self.state.output_dir = run_dir / self.state.run_id
        self.state.output_dir.mkdir(parents=True, exist_ok=True)

        configure_logger(settings.log_level, log_file=self.state.output_dir / "run.log")
        self.log = get_logger("orchestrator")

    # ---- state helpers ----
    def update_state(self, key: str, value) -> None:
        setattr(self.state, key, value)
        self.state.persist()

    def get_state(self, key: str):
        return getattr(self.state, key, None)

    # ---- pipeline ----
    def run(self, user_guide_path: Path | None = None) -> SessionState:
        log_event(self.log, "run.start", run_id=self.state.run_id, output=str(self.state.output_dir))

        # 1. Analyst
        log_event(self.log, "stage", stage="analyst")
        analyst = AnalystAgent(settings.analyst, verbose=self.verbose)
        self.state.app_analysis = analyst.analyze(self.state, user_guide_path=user_guide_path)
        self.state.persist()
        log_event(self.log, "analyst.done",
                  framework=self.state.app_analysis.framework,
                  routes=len(self.state.app_analysis.routes),
                  workflows=len(self.state.app_analysis.workflows))

        # 2. UI Explorer (shares a single Playwright session)
        log_event(self.log, "stage", stage="ui_explorer")
        explorer_toolbox = PlaywrightToolbox(screenshot_dir=self.state.output_dir / "screenshots")
        explorer = UIExplorerAgent(settings.ui_explorer, explorer_toolbox, verbose=self.verbose)
        self.state.ui_map = explorer.explore(self.state, self.state.app_analysis)
        self.state.persist()
        log_event(self.log, "ui_explorer.done",
                  pages=len(self.state.ui_map.pages),
                  workflows=len(self.state.ui_map.workflows))

        # 3. Code Generator
        log_event(self.log, "stage", stage="codegen")
        codegen = CodeGeneratorAgent(settings.codegen, verbose=self.verbose)
        self.state.artifacts = codegen.generate(self.state, self.state.app_analysis, self.state.ui_map)
        self.state.persist()
        log_event(self.log, "codegen.done",
                  automation=str(self.state.artifacts.automation_dir),
                  manual=str(self.state.artifacts.manual_tests_path))

        # 4. Executor (self-healing)
        log_event(self.log, "stage", stage="executor")
        exec_toolbox = PlaywrightToolbox(screenshot_dir=self.state.output_dir / "exec_screenshots")
        executor = ExecutorAgent(settings.executor, exec_toolbox, verbose=self.verbose)
        self.state.execution = executor.execute(self.state)
        self.state.persist()
        log_event(self.log, "executor.done",
                  passed=self.state.execution.passed,
                  failed=self.state.execution.failed,
                  fixed=self.state.execution.fixed)

        log_event(self.log, "run.done", report=str(self.state.execution.report_path))
        return self.state
