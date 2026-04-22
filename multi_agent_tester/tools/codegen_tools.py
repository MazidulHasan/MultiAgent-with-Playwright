"""Tools used by the Code Generator Agent — render Jinja2 templates into
manual test markdown and a Playwright POM automation project.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.tools import tool

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(disabled_extensions=("py", "md", "ini", "cfg")),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def _render(template_name: str, **ctx: Any) -> str:
    return _env.get_template(template_name).render(**ctx)


@tool
def generate_page_object(output_dir: str, page_name: str, elements_json: str, base_url: str = "") -> str:
    """Render a Page Object class file.

    `elements_json` is a JSON array of {name, locator_expression, strategy, type, description}.
    Returns the absolute path of the written file.
    """
    try:
        elements = json.loads(elements_json)
    except json.JSONDecodeError as e:
        return f"ERROR: invalid elements_json: {e}"

    out = Path(output_dir) / "automation" / "pages"
    out.mkdir(parents=True, exist_ok=True)
    class_name = _pascal(page_name) + "Page"
    file_path = out / f"{_snake(page_name)}_page.py"

    code = _render(
        "page_object.py.j2",
        class_name=class_name,
        page_name=page_name,
        elements=elements,
        base_url=base_url,
    )
    file_path.write_text(code, encoding="utf-8")
    return str(file_path)


@tool
def generate_test_file(output_dir: str, workflow_name: str, steps_json: str, page_imports_json: str) -> str:
    """Render a pytest-Playwright test for one workflow.

    `steps_json`: [{action, target, value?, assertion?}, ...]
    `page_imports_json`: [{module, class_name, attr_name}, ...]
    """
    try:
        steps = json.loads(steps_json)
        imports = json.loads(page_imports_json)
    except json.JSONDecodeError as e:
        return f"ERROR: invalid json: {e}"

    out = Path(output_dir) / "automation" / "tests"
    out.mkdir(parents=True, exist_ok=True)
    fname = f"test_{_snake(workflow_name)}.py"
    fp = out / fname
    code = _render(
        "test_file.py.j2",
        workflow_name=workflow_name,
        test_func_name="test_" + _snake(workflow_name),
        steps=steps,
        imports=imports,
    )
    fp.write_text(code, encoding="utf-8")
    return str(fp)


@tool
def generate_project_scaffold(output_dir: str, base_url: str, credentials_json: str = "{}") -> str:
    """Write base_page.py, conftest.py, pytest.ini, utils/commands.py, utils/data_generator.py.

    `credentials_json` is stored as default creds in conftest (values also overridable via env).
    Returns the automation dir path.
    """
    try:
        creds = json.loads(credentials_json) if credentials_json else {}
    except json.JSONDecodeError:
        creds = {}
    automation = Path(output_dir) / "automation"
    (automation / "pages").mkdir(parents=True, exist_ok=True)
    (automation / "tests").mkdir(parents=True, exist_ok=True)
    (automation / "utils").mkdir(parents=True, exist_ok=True)

    files = {
        automation / "pages" / "__init__.py": "",
        automation / "tests" / "__init__.py": "",
        automation / "utils" / "__init__.py": "",
        automation / "pages" / "base_page.py": _render("base_page.py.j2", base_url=base_url),
        automation / "conftest.py": _render("conftest.py.j2", base_url=base_url, credentials=creds),
        automation / "pytest.ini": _render("pytest.ini.j2"),
        automation / "utils" / "commands.py": _render("commands.py.j2"),
        automation / "utils" / "data_generator.py": _render("data_generator.py.j2"),
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    return str(automation)


@tool
def generate_manual_tests(output_dir: str, test_cases_json: str) -> str:
    """Render a Markdown manual test suite from a JSON array of test cases.

    Each case: {id, title, priority, preconditions, steps[], expected, type}
    """
    try:
        cases = json.loads(test_cases_json)
    except json.JSONDecodeError as e:
        return f"ERROR: invalid json: {e}"

    out = Path(output_dir) / "manual_tests"
    out.mkdir(parents=True, exist_ok=True)
    md_path = out / "regression_tests.md"
    md_path.write_text(_render("manual_tests.md.j2", cases=cases), encoding="utf-8")

    # Optional xlsx — nice for QA teams
    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Regression"
        ws.append(["ID", "Title", "Priority", "Type", "Preconditions", "Steps", "Expected"])
        for c in cases:
            ws.append([
                c.get("id", ""), c.get("title", ""), c.get("priority", ""),
                c.get("type", ""), c.get("preconditions", ""),
                "\n".join(c.get("steps", [])), c.get("expected", ""),
            ])
        xlsx_path = out / "regression_tests.xlsx"
        wb.save(str(xlsx_path))
    except Exception:  # noqa: BLE001
        pass
    return str(md_path)


@tool
def validate_python_syntax(file_path: str) -> str:
    """Parse a Python file and report syntax validity. Returns 'OK' or error string."""
    try:
        ast.parse(Path(file_path).read_text(encoding="utf-8"))
        return "OK"
    except SyntaxError as e:
        return f"SYNTAX_ERROR: {e}"
    except OSError as e:
        return f"READ_ERROR: {e}"


# ---- helpers ----

def _snake(s: str) -> str:
    import re
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s or "page"


def _pascal(s: str) -> str:
    return "".join(p.capitalize() for p in _snake(s).split("_"))


CODEGEN_TOOLS = [
    generate_page_object,
    generate_test_file,
    generate_project_scaffold,
    generate_manual_tests,
    validate_python_syntax,
]
