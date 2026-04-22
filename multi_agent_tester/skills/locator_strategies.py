"""Pick the most resilient locator for a given DOM element, Playwright-style.

Priority (matches Playwright docs + SauceDemo conventions):
    1. data-test / data-testid
    2. getByRole(role, name=accessible-name)
    3. getByLabel / associated <label>
    4. getByPlaceholder
    5. stable id / name attribute
    6. text content (for buttons/links without role-friendly names)
    7. fallback CSS selector
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LocatorSuggestion:
    strategy: str          # 'data-test' | 'role' | 'label' | 'placeholder' | 'id' | 'text' | 'css'
    expression: str        # Python code expression, e.g. 'page.get_by_role("button", name="Login")'
    raw_selector: str      # Equivalent CSS/attribute selector for POM fallback


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def suggest_locator(attrs: dict[str, str], tag: str, text: str, role: str | None = None) -> LocatorSuggestion:
    """Given an element's attributes, tag, text, and ARIA role, pick the best locator."""
    a = {k.lower(): v for k, v in attrs.items() if v is not None}
    tag = tag.lower()

    # 1. data-test attributes
    for key in ("data-test", "data-testid", "data-test-id", "data-qa", "data-cy"):
        if a.get(key):
            val = a[key]
            return LocatorSuggestion(
                strategy="data-test",
                expression=f'page.get_by_test_id("{_escape(val)}")',
                raw_selector=f'[{key}="{val}"]',
            )

    # 2. ARIA role with accessible name
    effective_role = role or _implicit_role(tag, a)
    name = a.get("aria-label") or text.strip()
    if effective_role and name:
        return LocatorSuggestion(
            strategy="role",
            expression=f'page.get_by_role("{effective_role}", name="{_escape(name[:80])}")',
            raw_selector=f'{tag}',
        )

    # 3. Label association (input with id referenced by a <label for=...>)
    if tag in ("input", "textarea", "select") and a.get("aria-labelledby"):
        label = a["aria-labelledby"]
        return LocatorSuggestion(
            strategy="label",
            expression=f'page.get_by_label("{_escape(label)}")',
            raw_selector=f'[aria-labelledby="{label}"]',
        )

    # 4. Placeholder
    if a.get("placeholder"):
        return LocatorSuggestion(
            strategy="placeholder",
            expression=f'page.get_by_placeholder("{_escape(a["placeholder"])}")',
            raw_selector=f'[placeholder="{a["placeholder"]}"]',
        )

    # 5. id / name
    if a.get("id"):
        return LocatorSuggestion(
            strategy="id",
            expression=f'page.locator("#{a["id"]}")',
            raw_selector=f'#{a["id"]}',
        )
    if a.get("name"):
        return LocatorSuggestion(
            strategy="id",
            expression=f'page.locator("[name=\\"{a["name"]}\\"]")',
            raw_selector=f'[name="{a["name"]}"]',
        )

    # 6. Text
    if text.strip() and tag in ("a", "button", "span", "div", "li"):
        t = text.strip()[:60]
        return LocatorSuggestion(
            strategy="text",
            expression=f'page.get_by_text("{_escape(t)}", exact=True)',
            raw_selector=f'{tag}:has-text("{t}")',
        )

    # 7. CSS fallback
    cls = a.get("class", "").split()[0] if a.get("class") else ""
    fallback = f'{tag}.{cls}' if cls else tag
    return LocatorSuggestion(
        strategy="css",
        expression=f'page.locator("{_escape(fallback)}")',
        raw_selector=fallback,
    )


def _implicit_role(tag: str, attrs: dict[str, str]) -> str | None:
    """Implicit ARIA role lookup for common tags."""
    if tag == "button":
        return "button"
    if tag == "a" and attrs.get("href"):
        return "link"
    if tag == "input":
        t = (attrs.get("type") or "text").lower()
        return {"submit": "button", "button": "button", "checkbox": "checkbox",
                "radio": "radio", "text": "textbox", "email": "textbox",
                "password": "textbox", "search": "searchbox"}.get(t, "textbox")
    if tag == "textarea":
        return "textbox"
    if tag == "select":
        return "combobox"
    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        return "heading"
    if tag == "img":
        return "img"
    return None
