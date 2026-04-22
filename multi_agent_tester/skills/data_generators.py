"""Synthesize plausible form-fill data based on field name/type."""
from __future__ import annotations

import re
import secrets
import string
from datetime import datetime


def generate_value(field_name: str, field_type: str = "text", placeholder: str = "") -> str:
    """Best-effort value for a form field."""
    name = (field_name + " " + placeholder).lower()

    if field_type == "email" or "email" in name:
        suffix = secrets.token_hex(3)
        return f"qa.user.{suffix}@example.com"
    if field_type == "password" or "password" in name:
        return "Test1234!"
    if field_type in ("tel", "phone") or "phone" in name:
        return "5551234567"
    if field_type == "number" or re.search(r"\b(qty|quantity|amount|count|age)\b", name):
        return "1"
    if field_type == "date":
        return datetime.now().strftime("%Y-%m-%d")
    if "first" in name and "name" in name:
        return "Test"
    if "last" in name and "name" in name:
        return "User"
    if "name" in name:
        return "Test User"
    if re.search(r"\bzip|postal\b", name):
        return "94016"
    if "city" in name:
        return "San Francisco"
    if "address" in name:
        return "1 Market Street"
    if "url" in name:
        return "https://example.com"

    # Default: short token
    return "test-" + "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def unique_email(prefix: str = "qa") -> str:
    return f"{prefix}.{secrets.token_hex(4)}@example.com"
