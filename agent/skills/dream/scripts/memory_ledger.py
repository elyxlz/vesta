#!/usr/bin/env python3
"""Report rules that vanished from MEMORY.md between nightly curations.

Curation rewrites MEMORY.md in place and the file is committed only occasionally, so a rule
written one night and compressed away the next leaves no trace in git or anywhere else. This keeps
its own dated snapshots and diffs against the most recent one.

`### User State` is excluded by design: the dream skill calls it a snapshot to be replaced rather
than appended, so its churn is expected and would bury the signal. Everything else in MEMORY.md is
meant to be durable, so a line leaving it is a decision that should be made on purpose.

    memory_ledger.py            report what left since the last snapshot
    memory_ledger.py --snapshot record today's MEMORY.md as the new baseline
"""

import datetime as dt
import difflib
import pathlib as pl
import sys

MEMORY = pl.Path("~/agent/MEMORY.md").expanduser()
SNAPS = pl.Path("~/agent/data/memory-snapshots").expanduser()
# The one section the dream skill explicitly tells you to replace wholesale each night.
VOLATILE = "### User State"
KEEP = 30


def durable_lines(text: str) -> list[str]:
    """Every non-blank line outside the volatile section, so churn there cannot mask a real loss."""
    out, skipping = [], False
    for line in text.splitlines():
        if line.startswith("### "):
            skipping = line.strip() == VOLATILE
        if not skipping and line.strip():
            out.append(line.rstrip())
    return out


def latest_snapshot() -> pl.Path | None:
    return max(SNAPS.glob("*.md"), default=None)


def snapshot() -> int:
    SNAPS.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d")
    (SNAPS / f"{stamp}.md").write_text(MEMORY.read_text())
    for old in sorted(SNAPS.glob("*.md"))[:-KEEP]:
        old.unlink()
    print(f"snapshot saved: {stamp}.md ({len(sorted(SNAPS.glob('*.md')))} kept)")
    return 0


def report() -> int:
    prev = latest_snapshot()
    if prev is None:
        print("no prior snapshot; run --snapshot to start the ledger")
        return 0
    before, after = durable_lines(prev.read_text()), durable_lines(MEMORY.read_text())
    gone = [ln[2:] for ln in difflib.ndiff(before, after) if ln.startswith("- ")]
    added = sum(1 for ln in difflib.ndiff(before, after) if ln.startswith("+ "))
    print(f"vs {prev.name}: {len(gone)} durable line(s) gone, {added} added")
    if not gone:
        return 0
    print("\nReview each. A rule leaving MEMORY.md is only safe if it graduated into a skill file")
    print("(say which) or genuinely expired. Anything else is the loop deleting its own output.\n")
    for line in gone:
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    sys.exit(snapshot() if "--snapshot" in sys.argv[1:] else report())
