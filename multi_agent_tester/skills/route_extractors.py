"""Framework-specific skills for extracting routes, models, auth patterns.

Each function returns a partial AppAnalysis-shaped dict so the Analyst agent can
merge them. These skills are deterministic (regex/AST) so the LLM doesn't need to
re-derive them each run — it uses them as grounded facts.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from ..utils.fs import iter_source_files, safe_read


FRAMEWORK_SIGNATURES = [
    ("django", [r"django", r"from django", r"INSTALLED_APPS"]),
    ("flask", [r"from flask import", r"Flask\("]),
    ("fastapi", [r"from fastapi import", r"FastAPI\("]),
    ("express", [r"require\(['\"]express['\"]\)", r"from ['\"]express['\"]"]),
    ("nextjs", [r"next/router", r"next\.config\.js"]),
    ("react", [r"\"react\"\s*:", r"from ['\"]react['\"]"]),
    ("rails", [r"Rails::Application", r"config/routes\.rb"]),
    ("laravel", [r"Illuminate\\\\", r"Route::get"]),
    ("spring", [r"@SpringBootApplication", r"@RestController"]),
]


def detect_framework(repo: Path) -> str:
    """Return the best-matched framework name, or 'unknown'."""
    # Strong signal: package.json dependencies
    pkg = repo / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            if "next" in deps:
                return "nextjs"
            if "express" in deps:
                return "express"
            if "react" in deps:
                return "react"
        except (OSError, json.JSONDecodeError):
            pass

    scores: dict[str, int] = {}
    for fp in iter_source_files(repo, max_files=400):
        text = safe_read(fp, max_bytes=50_000)
        for name, patterns in FRAMEWORK_SIGNATURES:
            for pat in patterns:
                if re.search(pat, text):
                    scores[name] = scores.get(name, 0) + 1
    if not scores:
        return "unknown"
    return max(scores, key=scores.get)


def extract_django_routes(repo: Path) -> list[str]:
    routes: list[str] = []
    for fp in repo.rglob("urls.py"):
        text = safe_read(fp)
        routes.extend(re.findall(r"path\(\s*['\"]([^'\"]+)['\"]", text))
        routes.extend(re.findall(r"url\(\s*r?['\"]\^?([^'\"$]+)", text))
    return sorted(set("/" + r.lstrip("/") for r in routes if r))


def extract_flask_fastapi_routes(repo: Path) -> list[str]:
    routes: list[str] = []
    for fp in iter_source_files(repo, max_files=500):
        if fp.suffix != ".py":
            continue
        text = safe_read(fp)
        # @app.get("/x"), @router.post("/y"), @app.route("/z")
        routes.extend(re.findall(r"@\w+\.(?:get|post|put|patch|delete|route)\(\s*['\"]([^'\"]+)", text))
    return sorted(set(routes))


def extract_express_routes(repo: Path) -> list[str]:
    routes: list[str] = []
    for fp in iter_source_files(repo, max_files=500):
        if fp.suffix not in (".js", ".ts", ".jsx", ".tsx"):
            continue
        text = safe_read(fp)
        routes.extend(re.findall(r"\b(?:app|router)\.(?:get|post|put|patch|delete|use)\(\s*['\"]([^'\"]+)", text))
    return sorted(set(routes))


def extract_react_routes(repo: Path) -> list[str]:
    """React Router v6 <Route path="..."> declarations."""
    routes: list[str] = []
    for fp in iter_source_files(repo, max_files=800):
        if fp.suffix not in (".js", ".ts", ".jsx", ".tsx"):
            continue
        text = safe_read(fp)
        routes.extend(re.findall(r"<Route[^>]+path=['\"]([^'\"]+)['\"]", text))
        # Plain window.location / navigate('/...') hints
        routes.extend(re.findall(r"navigate\(\s*['\"](/[a-zA-Z0-9/_.-]*)", text))
    return sorted(set(routes))


def extract_routes(repo: Path, framework: str) -> list[str]:
    match framework:
        case "django":
            return extract_django_routes(repo)
        case "flask" | "fastapi":
            return extract_flask_fastapi_routes(repo)
        case "express" | "nextjs":
            return extract_express_routes(repo)
        case "react":
            return extract_react_routes(repo)
    return []


def extract_python_entities(repo: Path) -> list[str]:
    """Extract class names that look like models / entities via AST."""
    entities: set[str] = set()
    base_hints = {"Model", "BaseModel", "Base", "Document", "Schema"}
    for fp in iter_source_files(repo, max_files=500):
        if fp.suffix != ".py":
            continue
        text = safe_read(fp)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = {getattr(b, "id", None) or getattr(getattr(b, "attr", None), "__str__", lambda: "")()
                         for b in node.bases}
                if bases & base_hints or "models.Model" in text:
                    entities.add(node.name)
    return sorted(entities)
