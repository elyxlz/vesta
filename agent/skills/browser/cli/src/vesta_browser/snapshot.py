"""Accessibility-tree snapshot with numbered refs (e1, e2, ...).

BiDi has no native AX-tree export, so the snapshot is reconstructed in-page: the
vendored accname/role engine (vendor/snapshot_accname.js, bundled from
dom-accessibility-api) walks the DOM, computes each element's role + accessible
name, assigns refs to interactive elements, and returns the indented tree as a JSON
string. The ref -> element map lives in the page realm (window.__vestaRefs), so a
later `browser click e5` in a fresh CLI process resolves the ref by re-reading that
map through the same long-lived Camoufox, no Python-side ref store needed. Refs
invalidate on navigation exactly as the CDP backend-node ids did.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

from .admin import send

_BUNDLE_PATH = Path(__file__).parent / "vendor" / "snapshot_accname.js"


@functools.cache
def _bundle() -> str:
    return _BUNDLE_PATH.read_text()


def _eval_json(expression: str):
    """Run a script.evaluate whose completion value is a JSON string; return it parsed.
    Context is injected by the daemon."""
    resp = send({"method": "script.evaluate", "params": {"expression": expression, "awaitPromise": True}})
    result = resp["result"] if "result" in resp else {}
    if "type" not in result:
        raise RuntimeError(f"unexpected script.evaluate response: {result!r}")
    if result["type"] == "exception":
        detail = result["exceptionDetails"]["text"] if "exceptionDetails" in result else "unknown"
        raise RuntimeError(f"snapshot script raised: {detail}")
    value = result["result"]
    if value["type"] in ("undefined", "null"):
        return None
    return json.loads(value["value"])


def _current_context() -> str:
    resp = send({"meta": "context"})
    return resp["context"] if resp.get("context") else ""


def snapshot(
    interactive_only: bool = False,
    max_depth: int = 50,
) -> dict:
    """Take a new accessibility snapshot. Returns {text, refs, target_id, url, title}."""
    opts = {"interactive_only": interactive_only, "max_depth": max_depth}
    # Reinstall the walker (idempotent, cheap) then invoke it; the trailing expression
    # is the completion value script.evaluate returns.
    expression = f"{_bundle()}\nJSON.stringify(globalThis.__vestaSnapshot({json.dumps(opts)}))"
    data = _eval_json(expression)
    if data is None:
        raise RuntimeError("snapshot returned no data (no document body?)")
    return {
        "target_id": _current_context(),
        "url": data["url"],
        "title": data["title"],
        "text": data["text"],
        "refs": data["refs"],
        "ref_count": data["ref_count"],
    }
