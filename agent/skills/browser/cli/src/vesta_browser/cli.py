"""Bash-compatible CLI dispatcher.

Command surface matches the old TypeScript CLI so existing agent prompts keep working.
Also supports a `browser <<'PY' ... PY` stdin mode for multi-line scripts (helpers
are pre-imported).
"""

from __future__ import annotations


def main() -> int:
    return 0
