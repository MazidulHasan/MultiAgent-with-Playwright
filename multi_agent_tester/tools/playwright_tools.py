"""Playwright-backed UI exploration tools bound to a single live browser session.

Wrapping these in a class (rather than free `@tool` functions) lets all tools
share one browser/page pair — agents call `navigate`, then `get_interactive_elements`
on the same page. Each method is exposed as a LangChain StructuredTool via
`as_tools()`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..skills.data_generators import generate_value
from ..skills.locator_strategies import suggest_locator
from ..utils.logger import get_logger

log = get_logger(__name__)


class PlaywrightToolbox:
    """Live Playwright session exposed as LangChain tools."""

    def __init__(self, screenshot_dir: Path):
        self.screenshot_dir = screenshot_dir
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None
        self._visited: list[str] = []
        self._base_url: str = ""

    def _resolve_url(self, url: str) -> str:
        """Turn a relative path like /login into an absolute URL using the base URL."""
        if url.startswith("http://") or url.startswith("https://"):
            return url
        base = self._base_url.rstrip("/")
        return base + "/" + url.lstrip("/")

    # ---------------- lifecycle ----------------

    def launch(self, url: str, browser: str = "chromium", headless: bool = False) -> str:
        from playwright.sync_api import sync_playwright

        if self._pw is None:
            self._pw = sync_playwright().start()
        if self._browser is None:
            launcher = getattr(self._pw, browser)
            self._browser = launcher.launch(headless=headless)
            self._context = self._browser.new_context()
            self.page = self._context.new_page()
        abs_url = self._resolve_url(url)
        # Store origin as base URL (e.g. http://localhost:3000)
        from urllib.parse import urlparse
        parsed = urlparse(abs_url)
        self._base_url = f"{parsed.scheme}://{parsed.netloc}"
        self.page.goto(abs_url, wait_until="domcontentloaded")
        self._visited.append(self.page.url)
        return f"OK: loaded {self.page.url} (title={self.page.title()!r})"

    def close(self) -> str:
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        finally:
            self._pw = self._browser = self._context = self.page = None
        return "OK: closed"

    # ---------------- navigation ----------------

    def navigate(self, url: str) -> str:
        """Navigate the current page to url. Relative paths like /login are resolved against the base URL."""
        self._require_page()
        abs_url = self._resolve_url(url)
        self.page.goto(abs_url, wait_until="domcontentloaded")
        self._visited.append(self.page.url)
        return f"OK: {self.page.url} (title={self.page.title()!r})"

    def current_url(self) -> str:
        self._require_page()
        return self.page.url

    # ---------------- introspection ----------------

    def get_page_structure(self, max_chars: int = 8000) -> str:
        """Return a compact outline of interactive landmarks on the current page."""
        self._require_page()
        js = r"""
        () => {
          const out = [];
          const sel = 'a, button, input, select, textarea, [role], form, nav, header, footer, h1, h2, h3, [data-test], [data-testid]';
          document.querySelectorAll(sel).forEach(el => {
            const r = el.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) return;
            out.push({
              tag: el.tagName.toLowerCase(),
              role: el.getAttribute('role') || null,
              text: (el.innerText || el.value || '').trim().slice(0, 80),
              attrs: {
                id: el.id || null,
                name: el.getAttribute('name'),
                type: el.getAttribute('type'),
                placeholder: el.getAttribute('placeholder'),
                href: el.getAttribute('href'),
                'data-test': el.getAttribute('data-test'),
                'data-testid': el.getAttribute('data-testid'),
                'aria-label': el.getAttribute('aria-label'),
                class: el.getAttribute('class'),
              }
            });
          });
          return out;
        }
        """
        elements = self.page.evaluate(js)
        payload = json.dumps(elements, ensure_ascii=False)
        return payload[:max_chars] + ("…" if len(payload) > max_chars else "")

    def get_interactive_elements(self) -> str:
        """Return JSON array of {name, tag, locator_expression, strategy, type, description}."""
        self._require_page()
        raw = json.loads(self.get_page_structure(max_chars=200_000))
        enriched: list[dict[str, Any]] = []
        seen: set[str] = set()
        for i, el in enumerate(raw):
            attrs = {k: v for k, v in (el.get("attrs") or {}).items() if v}
            sug = suggest_locator(attrs, el["tag"], el.get("text", ""), el.get("role"))
            name = (
                attrs.get("data-test")
                or attrs.get("data-testid")
                or attrs.get("id")
                or attrs.get("name")
                or el.get("text") and el["text"][:40]
                or f"{el['tag']}_{i}"
            )
            key = f"{sug.strategy}:{sug.raw_selector}"
            if key in seen:
                continue
            seen.add(key)
            enriched.append({
                "name": _snake(name),
                "tag": el["tag"],
                "type": attrs.get("type") or el.get("role") or el["tag"],
                "locator_expression": sug.expression,
                "raw_selector": sug.raw_selector,
                "strategy": sug.strategy,
                "text": el.get("text", ""),
            })
        return json.dumps(enriched[:200])

    # ---------------- interactions ----------------

    def click_element(self, selector: str) -> str:
        """Click element by CSS/text selector. Waits for visibility first."""
        self._require_page()
        self.page.wait_for_selector(selector, state="visible", timeout=10_000)
        self.page.click(selector)
        return f"OK: clicked {selector}"

    def fill_form(self, data: dict[str, str]) -> str:
        """Fill multiple fields. Keys are CSS selectors, values are text to enter."""
        self._require_page()
        for sel, val in data.items():
            try:
                self.page.fill(sel, val)
            except Exception as e:  # noqa: BLE001
                return f"ERROR: failed to fill {sel}: {e}"
        return f"OK: filled {len(data)} field(s)"

    def smart_fill_form(self, form_selector: str = "form") -> str:
        """Auto-fill all visible fields in a form with plausible synthetic data."""
        self._require_page()
        js = r"""
        (sel) => {
          const form = document.querySelector(sel) || document;
          const fields = [];
          form.querySelectorAll('input, textarea, select').forEach(el => {
            if (el.type === 'hidden' || el.disabled) return;
            fields.push({
              selector: el.id ? '#' + el.id : (el.name ? `[name="${el.name}"]` : el.tagName.toLowerCase()),
              name: el.name || el.id || el.placeholder || '',
              type: el.type || el.tagName.toLowerCase(),
              placeholder: el.placeholder || '',
            });
          });
          return fields;
        }
        """
        fields = self.page.evaluate(js, form_selector)
        filled = 0
        for f in fields:
            val = generate_value(f.get("name", ""), f.get("type", "text"), f.get("placeholder", ""))
            try:
                self.page.fill(f["selector"], val)
                filled += 1
            except Exception:  # noqa: BLE001
                continue
        return f"OK: auto-filled {filled}/{len(fields)} fields"

    def wait_for_navigation(self, timeout_ms: int = 10_000) -> str:
        self._require_page()
        try:
            self.page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception as e:  # noqa: BLE001
            return f"WARN: {e}"
        return f"OK: url={self.page.url}"

    def capture_screenshot(self, label: str) -> str:
        self._require_page()
        name = "".join(c if c.isalnum() else "_" for c in label)[:60]
        path = self.screenshot_dir / f"{name}.png"
        self.page.screenshot(path=str(path), full_page=True)
        return str(path)

    def relocate_element(self, description: str) -> str:
        """Find an element matching a natural description — used by self-healing.

        Scans all visible interactive elements and scores by description overlap
        with (text, aria-label, id, data-test, placeholder). Returns the best
        locator expression or an error.
        """
        self._require_page()
        raw = json.loads(self.get_interactive_elements())
        kws = {w for w in _tokens(description) if w}

        def score(el: dict[str, Any]) -> int:
            hay = _tokens(" ".join([
                el.get("name", ""), el.get("text", ""), el.get("raw_selector", ""),
                el.get("type", ""),
            ]))
            return len(kws & hay)

        ranked = sorted(raw, key=score, reverse=True)
        if not ranked or score(ranked[0]) == 0:
            return "ERROR: no match found"
        best = ranked[0]
        return json.dumps({
            "locator_expression": best["locator_expression"],
            "raw_selector": best["raw_selector"],
            "strategy": best["strategy"],
            "name": best["name"],
        })

    # ---------------- helpers ----------------

    def _require_page(self):
        if self.page is None:
            raise RuntimeError("Browser not launched. Call launch(url) first.")

    # ---------------- bind as LangChain tools ----------------

    def as_tools(self) -> list[StructuredTool]:
        return [
            StructuredTool.from_function(
                func=self.launch,
                name="launch_browser",
                description="Launch browser and open URL. Required before other Playwright tools.",
                args_schema=_LaunchArgs,
            ),
            StructuredTool.from_function(self.navigate, name="navigate_to",
                description="Navigate current page to URL.", args_schema=_NavArgs),
            StructuredTool.from_function(self.current_url, name="current_url",
                description="Return current page URL."),
            StructuredTool.from_function(self.get_page_structure, name="get_page_structure",
                description="Get compact JSON outline of interactive elements on current page."),
            StructuredTool.from_function(self.get_interactive_elements, name="get_interactive_elements",
                description="Return ranked list of interactive elements with recommended Playwright locators."),
            StructuredTool.from_function(self.click_element, name="click_element",
                description="Click element matching a CSS selector.", args_schema=_SelArgs),
            StructuredTool.from_function(self.fill_form, name="fill_form",
                description="Fill a form with {selector: value} dict.", args_schema=_FillArgs),
            StructuredTool.from_function(self.smart_fill_form, name="smart_fill_form",
                description="Auto-fill a form using inferred field types.", args_schema=_FormSelArgs),
            StructuredTool.from_function(self.wait_for_navigation, name="wait_for_navigation",
                description="Wait for network idle after an action."),
            StructuredTool.from_function(self.capture_screenshot, name="capture_screenshot",
                description="Take a full-page screenshot and return its path.", args_schema=_LabelArgs),
            StructuredTool.from_function(self.relocate_element, name="relocate_element",
                description="Find updated locator for an element described in natural language. Used for self-healing.",
                args_schema=_DescArgs),
            StructuredTool.from_function(self.close, name="close_browser",
                description="Close the browser session."),
        ]


# -- arg schemas ----------------------------------------------------------

class _LaunchArgs(BaseModel):
    url: str = Field(..., description="URL to open")
    browser: str = Field("chromium", description="chromium | firefox | webkit")
    headless: bool = Field(False, description="Run headless")


class _NavArgs(BaseModel):
    url: str


class _SelArgs(BaseModel):
    selector: str


class _FillArgs(BaseModel):
    data: dict[str, str]


class _FormSelArgs(BaseModel):
    form_selector: str = Field("form", description="CSS selector for the form")


class _LabelArgs(BaseModel):
    label: str


class _DescArgs(BaseModel):
    description: str = Field(..., description="Natural-language description of the element, e.g. 'login submit button'")


def _snake(s: str) -> str:
    import re
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s or "element"


def _tokens(s: str) -> set[str]:
    import re
    return set(t for t in re.split(r"[^a-zA-Z0-9]+", s.lower()) if len(t) > 1)
