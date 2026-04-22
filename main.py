"""CLI entry point for the multi-agent regression tester."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from multi_agent_tester.orchestrator import Orchestrator
from multi_agent_tester.state import UserInput

app = typer.Typer(add_completion=False, help="Multi-agent regression tester for web apps.")
console = Console()


@app.command()
def run(
    repo_path: Path = typer.Option(..., "--repo", "-r", help="Absolute path to the web app repo"),
    app_url: str = typer.Option(..., "--url", "-u", help="Live URL of the running app"),
    browser: str = typer.Option("chromium", help="chromium | firefox | webkit"),
    headless: bool = typer.Option(False, help="Run the browser headless"),
    username: Optional[str] = typer.Option(None, help="Login username"),
    password: Optional[str] = typer.Option(None, help="Login password"),
    workers: int = typer.Option(1, "--workers", "-w", help="pytest-xdist parallel workers"),
    user_guide: Optional[Path] = typer.Option(None, "--guide", help="Optional user guide (md/pdf/txt)"),
    config_file: Optional[Path] = typer.Option(None, "--config", help="JSON file matching the user-input schema"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Run the full Analyst → UI Explorer → Codegen → Executor pipeline."""
    if config_file:
        cfg = json.loads(config_file.read_text(encoding="utf-8"))
        user_input = UserInput(**cfg)
    else:
        creds = {}
        if username:
            creds["username"] = username
        if password:
            creds["password"] = password
        user_input = UserInput(
            repo_path=repo_path,
            app_url=app_url,
            browser=browser,
            headless=headless,
            credentials=creds,
            test_parallel_workers=workers,
        )

    orch = Orchestrator(user_input, verbose=verbose)
    state = orch.run(user_guide_path=user_guide)

    _print_summary(state)


def _print_summary(state) -> None:
    t = Table(title=f"Run {state.run_id}", show_header=True, header_style="bold")
    t.add_column("Metric")
    t.add_column("Value")
    t.add_row("Framework", state.app_analysis.framework)
    t.add_row("Routes discovered", str(len(state.app_analysis.routes)))
    t.add_row("Workflows", str(len(state.ui_map.workflows)))
    t.add_row("Pages mapped", str(len(state.ui_map.pages)))
    t.add_row("Manual cases", str(state.artifacts.manual_tests_path))
    t.add_row("Automation dir", str(state.artifacts.automation_dir))
    t.add_row("Tests passed", str(state.execution.passed))
    t.add_row("Tests failed", str(state.execution.failed))
    t.add_row("Auto-fixed", str(state.execution.fixed))
    t.add_row("Report", str(state.execution.report_path))
    console.print(t)


if __name__ == "__main__":
    app()
