"""Upstream-queue drain gate.

Root cause this kills: a prose rule the next run must remember to apply is a hope,
not a fix. The recurring failure is "fix" deferral with a rule, then defer again by
parking items in the upstream queue and treating "queued" as "done" -- the queue
becomes the new costume for deferral, with nothing enforcing the drain. This is the
executable gate that turns "drain the queue" into a hard condition.

Contract: every item under "## Open" in ~/agent/upstream-queue.md must be EITHER
  - filed (moved to "## Filed" with its PR/issue number), OR
  - carry an explicit `BLOCKED:` tag naming a tested blocker.
A bare open item (no BLOCKED tag) is an un-owned deferral and FAILS the gate.

Exit 0 = drained-or-blocked (dream may complete). Exit 1 = bare items remain.
Used two ways:
  1. dream SKILL.md completion gate: must exit 0 before mark_dreamer_complete.
  2. proactive-check backstop: fires independent of the dream, so a forgotten
     queue surfaces even if the dream never ran the gate.
"""

import re
import sys
from pathlib import Path

QUEUE = Path.home() / "agent" / "upstream-queue.md"


def bare_open_items(text: str) -> list[str]:
    """Open checklist items with no BLOCKED: tag (case-insensitive)."""
    in_open = False
    bare = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_open = stripped.lower().startswith("## open")
            continue
        if in_open and re.match(r"-\s*\[\s*\]", stripped):
            if "blocked:" not in stripped.lower():
                bare.append(stripped)
    return bare


def main() -> int:
    if not QUEUE.exists():
        print("queue-gate: no upstream-queue.md, nothing to drain. PASS")
        return 0
    bare = bare_open_items(QUEUE.read_text(encoding="utf-8"))
    if not bare:
        print("queue-gate: all open items filed or BLOCKED-tagged. PASS")
        return 0
    print(f"queue-gate: FAIL, {len(bare)} un-owned open item(s). File them or tag BLOCKED:<tested reason>:")
    for b in bare:
        print(f"  {b}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
