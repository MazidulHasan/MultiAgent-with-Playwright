"""Filesystem helpers used across tools."""
from __future__ import annotations

from pathlib import Path

_TEXT_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".rb", ".php", ".go", ".java", ".cs",
    ".html", ".htm", ".css", ".scss", ".json", ".yml", ".yaml", ".toml", ".ini",
    ".md", ".txt", ".env", ".cfg",
}

_IGNORE_DIRS = {
    "node_modules", ".git", "__pycache__", "dist", "build", ".next", ".venv",
    "venv", ".tox", ".pytest_cache", ".mypy_cache", "coverage", ".idea", ".vscode",
}


def is_text_source(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in _TEXT_EXTS


def iter_source_files(root: Path, max_files: int = 2000):
    """Yield source files under root, skipping common heavy directories."""
    count = 0
    for p in root.rglob("*"):
        if count >= max_files:
            return
        if any(part in _IGNORE_DIRS for part in p.parts):
            continue
        if is_text_source(p):
            yield p
            count += 1


def safe_read(path: Path, max_bytes: int = 200_000) -> str:
    try:
        data = path.read_bytes()[:max_bytes]
        return data.decode("utf-8", errors="replace")
    except OSError as e:
        return f"<<read error: {e}>>"
