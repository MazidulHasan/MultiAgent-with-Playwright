"""Shared session state passed between agents."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class UserInput(BaseModel):
    repo_path: Path
    app_url: str
    browser: str = "chromium"
    headless: bool = False
    credentials: dict[str, str] = Field(default_factory=dict)
    test_parallel_workers: int = 1
    max_self_heal_retries: int = 3


class PageElement(BaseModel):
    name: str
    selector: str
    locator_strategy: str  # data-test | role | label | css | text
    type: str  # input | button | link | dropdown | ...
    description: str = ""


class PageMap(BaseModel):
    name: str
    url: str
    title: str = ""
    elements: dict[str, PageElement] = Field(default_factory=dict)


class Workflow(BaseModel):
    name: str
    description: str = ""
    steps: list[str] = Field(default_factory=list)
    pages_involved: list[str] = Field(default_factory=list)
    playwright_snippet: str | None = None


class AppAnalysis(BaseModel):
    framework: str = "unknown"
    routes: list[str] = Field(default_factory=list)
    auth_required_routes: list[str] = Field(default_factory=list)
    auth_mechanism: str = "unknown"
    entities: list[str] = Field(default_factory=list)
    workflows: list[Workflow] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class UIMap(BaseModel):
    pages: dict[str, PageMap] = Field(default_factory=dict)
    workflows: list[Workflow] = Field(default_factory=list)


class GeneratedArtifacts(BaseModel):
    manual_tests_path: Path | None = None
    automation_dir: Path | None = None
    page_objects: list[str] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)


class FailureFix(BaseModel):
    test_name: str
    root_cause: str
    file_changed: str
    diff: str
    verified: bool = False


class ExecutionReport(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    fixed: int = 0
    skipped: int = 0
    fixes_applied: list[FailureFix] = Field(default_factory=list)
    unresolved_failures: list[dict[str, Any]] = Field(default_factory=list)
    report_path: Path | None = None


class SessionState(BaseModel):
    run_id: str = Field(default_factory=lambda: datetime.now().strftime("%Y%m%d-%H%M%S"))
    output_dir: Path
    user_input: UserInput
    app_analysis: AppAnalysis = Field(default_factory=AppAnalysis)
    ui_map: UIMap = Field(default_factory=UIMap)
    artifacts: GeneratedArtifacts = Field(default_factory=GeneratedArtifacts)
    execution: ExecutionReport = Field(default_factory=ExecutionReport)
    logs: list[str] = Field(default_factory=list)

    def persist(self) -> Path:
        """Write state to disk for crash recovery and inspection."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / "state.json"
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, output_dir: Path) -> "SessionState":
        data = json.loads((output_dir / "state.json").read_text(encoding="utf-8"))
        return cls.model_validate(data)
