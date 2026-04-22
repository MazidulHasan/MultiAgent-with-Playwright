"""LangChain tools the Analyst Agent uses to introspect a repo."""
from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import tool

from ..skills.route_extractors import (
    detect_framework,
    extract_python_entities,
    extract_routes,
)
from ..utils.fs import iter_source_files, safe_read


@tool
def list_directory(path: str, max_entries: int = 200) -> str:
    """List files and subdirectories at the given absolute path. Skips heavy dirs (node_modules, .git, etc)."""
    p = Path(path)
    if not p.exists():
        return f"ERROR: path does not exist: {path}"
    if p.is_file():
        return f"FILE: {path}"
    out: list[str] = []
    for child in sorted(p.iterdir()):
        if child.name in {"node_modules", ".git", "__pycache__", "dist", "build", ".venv", "venv"}:
            continue
        out.append(f"{'D' if child.is_dir() else 'F'}  {child.name}")
        if len(out) >= max_entries:
            out.append("... (truncated)")
            break
    return "\n".join(out) if out else "(empty)"


@tool
def read_file(path: str, max_chars: int = 20_000) -> str:
    """Read a text file. Use for source / config / docs. Truncated to max_chars."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return f"ERROR: not a file: {path}"
    return safe_read(p, max_bytes=max_chars)


@tool
def search_code(repo_path: str, pattern: str, max_results: int = 50) -> str:
    """Regex-search the repo for a pattern. Returns 'file:line: snippet' lines."""
    import re

    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"ERROR: bad regex: {e}"
    root = Path(repo_path)
    hits: list[str] = []
    for fp in iter_source_files(root, max_files=1000):
        try:
            for i, line in enumerate(safe_read(fp).splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{fp}:{i}: {line.strip()[:200]}")
                    if len(hits) >= max_results:
                        return "\n".join(hits) + "\n... (truncated)"
        except OSError:
            continue
    return "\n".join(hits) if hits else "(no matches)"


@tool
def detect_repo_framework(repo_path: str) -> str:
    """Identify the dominant backend/frontend framework in the repo."""
    return detect_framework(Path(repo_path))


@tool
def extract_app_routes(repo_path: str, framework: str) -> str:
    """Extract HTTP/UI route paths for the given framework. Returns JSON list."""
    routes = extract_routes(Path(repo_path), framework)
    return json.dumps(routes)


@tool
def extract_app_entities(repo_path: str) -> str:
    """Extract data-model class names (Python repos). Returns JSON list."""
    return json.dumps(extract_python_entities(Path(repo_path)))


@tool
def parse_documentation(path: str, max_chars: int = 30_000) -> str:
    """Read a Markdown / TXT / PDF user guide and return its text."""
    p = Path(path)
    if not p.exists():
        return f"ERROR: not found: {path}"
    if p.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            return "ERROR: pypdf not installed"
        reader = PdfReader(str(p))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return text[:max_chars]
    return safe_read(p, max_bytes=max_chars)


CODE_ANALYSIS_TOOLS = [
    list_directory,
    read_file,
    search_code,
    detect_repo_framework,
    extract_app_routes,
    extract_app_entities,
    parse_documentation,
]
