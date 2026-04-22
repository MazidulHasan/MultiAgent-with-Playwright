"""Execution + self-healing tools for the Executor Agent."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


@dataclass
class TestOutcome:
    name: str
    file: str
    status: str           # passed | failed | error | skipped
    duration: float = 0.0
    error_message: str = ""
    traceback: str = ""


@tool
def run_pytest(automation_dir: str, test_path: str = "", workers: int = 1, extra_args: str = "") -> str:
    """Run pytest in the automation dir. Returns JSON {returncode, stdout, stderr, junit_path, results[]}.

    `test_path` may be empty (run all), a directory, a file, or `file::test_name` for one test.
    """
    auto = Path(automation_dir)
    if not auto.exists():
        return json.dumps({"error": f"automation dir missing: {automation_dir}"})

    junit = auto / "test_results" / "junit.xml"
    junit.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["python", "-m", "pytest", "-v", f"--junitxml={junit}"]
    if workers > 1:
        cmd += ["-n", str(workers)]
    if extra_args:
        cmd += extra_args.split()
    if test_path:
        cmd.append(test_path)

    proc = subprocess.run(cmd, cwd=str(auto), capture_output=True, text=True, timeout=600)
    results = _parse_junit(junit) if junit.exists() else []

    return json.dumps({
        "returncode": proc.returncode,
        "stdout": proc.stdout[-8000:],
        "stderr": proc.stderr[-4000:],
        "junit_path": str(junit),
        "results": [r.__dict__ for r in results],
    })


@tool
def parse_test_failures(junit_path: str) -> str:
    """Re-parse a junit.xml file and return JSON list of failed tests with messages."""
    results = _parse_junit(Path(junit_path))
    failures = [r.__dict__ for r in results if r.status in ("failed", "error")]
    return json.dumps(failures)


@tool
def classify_failure(error_message: str, traceback: str) -> str:
    """Heuristically classify a failure as selector / timing / data / app_bug.

    Returns JSON {category, suggestion}. Cheap deterministic check the agent can
    use before asking the LLM for a fix proposal.
    """
    text = f"{error_message}\n{traceback}".lower()
    if any(s in text for s in ("locator", "selector", "no element matches", "strict mode violation",
                               "element is not attached", "element_not_found")):
        return json.dumps({"category": "selector",
                           "suggestion": "Re-discover the element via the UI explorer and update the page object."})
    if any(s in text for s in ("timeout", "timed out", "wait_for_selector", "waiting for")):
        return json.dumps({"category": "timing",
                           "suggestion": "Add explicit wait or increase timeout; verify the action precondition."})
    if any(s in text for s in ("unique constraint", "already exists", "duplicate", "conflict")):
        return json.dumps({"category": "data",
                           "suggestion": "Regenerate unique fixture data and retry."})
    if any(s in text for s in ("assertionerror", "expect(", "to be visible", "to have text", "to have url")):
        return json.dumps({"category": "assertion",
                           "suggestion": "Verify whether the application behavior changed; this may be a real bug."})
    return json.dumps({"category": "app_bug",
                       "suggestion": "Likely application-side. Capture for human review."})


@tool
def replace_in_file(file_path: str, old_snippet: str, new_snippet: str) -> str:
    """Apply a literal string replacement in a file. Used to patch a stale locator.

    Returns 'OK: N replacements' or an error.
    """
    p = Path(file_path)
    if not p.exists():
        return f"ERROR: not found: {file_path}"
    content = p.read_text(encoding="utf-8")
    if old_snippet not in content:
        return "ERROR: old_snippet not found in file (cannot patch safely)"
    new_content = content.replace(old_snippet, new_snippet)
    p.write_text(new_content, encoding="utf-8")
    return f"OK: {content.count(old_snippet)} replacements"


@tool
def write_execution_report(automation_dir: str, report_json: str) -> str:
    """Write an HTML execution report from a JSON summary.

    Schema: {total, passed, failed, fixed, skipped, fixes_applied[], unresolved_failures[]}
    """
    try:
        data = json.loads(report_json)
    except json.JSONDecodeError as e:
        return f"ERROR: bad json: {e}"

    auto = Path(automation_dir)
    out = auto / "test_results" / "execution_report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_render_html(data), encoding="utf-8")
    md = auto / "test_results" / "execution_report.md"
    md.write_text(_render_md(data), encoding="utf-8")
    return str(out)


# ----------------------------------------------------------------- helpers

def _parse_junit(path: Path) -> list[TestOutcome]:
    if not path.exists():
        return []
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError:
        return []
    out: list[TestOutcome] = []
    for case in root.iter("testcase"):
        status = "passed"
        msg = ""
        tb = ""
        if (failure := case.find("failure")) is not None:
            status, msg, tb = "failed", failure.get("message", ""), failure.text or ""
        elif (error := case.find("error")) is not None:
            status, msg, tb = "error", error.get("message", ""), error.text or ""
        elif case.find("skipped") is not None:
            status = "skipped"
        out.append(TestOutcome(
            name=case.get("name", ""),
            file=case.get("file", "") or case.get("classname", ""),
            status=status,
            duration=float(case.get("time", 0) or 0),
            error_message=msg[:1500],
            traceback=tb[:3000],
        ))
    return out


def _render_html(d: dict[str, Any]) -> str:
    fixes = "".join(
        f"<li><b>{f.get('test_name')}</b>: {f.get('root_cause')} → {f.get('file_changed')}</li>"
        for f in d.get("fixes_applied", [])
    ) or "<li>(none)</li>"
    fails = "".join(
        f"<li><b>{f.get('name')}</b><br><pre>{(f.get('error_message') or '')[:800]}</pre></li>"
        for f in d.get("unresolved_failures", [])
    ) or "<li>(none)</li>"
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>Execution Report</title>
<style>body{{font-family:system-ui;max-width:960px;margin:2em auto;padding:0 1em}}
.k{{display:inline-block;padding:.4em .8em;margin:.2em;border-radius:6px;color:#fff}}
.p{{background:#22a06b}}.f{{background:#c43c3c}}.x{{background:#3b82f6}}.s{{background:#888}}
pre{{background:#f4f4f4;padding:.6em;border-radius:4px;overflow:auto;max-height:280px}}</style>
</head><body>
<h1>Execution Report</h1>
<p>
  <span class='k p'>Passed {d.get('passed', 0)}</span>
  <span class='k f'>Failed {d.get('failed', 0)}</span>
  <span class='k x'>Auto-fixed {d.get('fixed', 0)}</span>
  <span class='k s'>Skipped {d.get('skipped', 0)}</span>
  &nbsp;Total: {d.get('total', 0)}
</p>
<h2>Self-healed</h2><ul>{fixes}</ul>
<h2>Unresolved failures</h2><ul>{fails}</ul>
</body></html>"""


def _render_md(d: dict[str, Any]) -> str:
    lines = [
        "# Execution Report",
        "",
        f"- Total: {d.get('total', 0)}",
        f"- Passed: {d.get('passed', 0)}",
        f"- Failed: {d.get('failed', 0)}",
        f"- Auto-fixed: {d.get('fixed', 0)}",
        f"- Skipped: {d.get('skipped', 0)}",
        "",
        "## Self-healed fixes",
    ]
    for f in d.get("fixes_applied", []) or [{"test_name": "(none)"}]:
        lines.append(f"- **{f.get('test_name')}** — {f.get('root_cause', '')} → `{f.get('file_changed', '')}`")
    lines += ["", "## Unresolved failures"]
    for f in d.get("unresolved_failures", []) or [{"name": "(none)"}]:
        lines.append(f"- **{f.get('name')}**")
        if f.get("error_message"):
            lines.append("  ```\n  " + (f.get("error_message") or "")[:600].replace("\n", "\n  ") + "\n  ```")
    return "\n".join(lines) + "\n"


EXECUTION_TOOLS = [
    run_pytest,
    parse_test_failures,
    classify_failure,
    replace_in_file,
    write_execution_report,
]
