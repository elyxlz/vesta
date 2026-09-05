"""The one slug rule: reduce a value to alphanumerics and underscores.

Every name this CLI derives from an address or a subject line (a save directory, a browser session)
goes through it, so one account maps to exactly one name wherever the name is built.
"""

from __future__ import annotations


def slug(value: str, *, fallback: str = "email") -> str:
    """Replace every non-alphanumeric character with `_`, trim the edges, and fall back when empty."""
    sanitized = "".join(char if char.isalnum() else "_" for char in value or "")
    return sanitized.strip("_") or fallback
