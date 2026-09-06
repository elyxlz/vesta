"""The one slug rule: reduce a value to alphanumerics and underscores.

Every save directory this CLI derives from an address or a subject line goes through it. The browser
session name is a separate contract, `capture.session_name`, shaped by the browser daemon.
"""

from __future__ import annotations


def slug(value: str, *, fallback: str = "email") -> str:
    """Replace every non-alphanumeric character with `_`, trim the edges, and fall back when empty."""
    sanitized = "".join(char if char.isalnum() else "_" for char in value or "")
    return sanitized.strip("_") or fallback
