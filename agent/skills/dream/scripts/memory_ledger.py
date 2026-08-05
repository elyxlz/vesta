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
# The two places the dream skill orders rewritten every night: the User State section, and the
# State paragraph opening the Self section (which runs to the --- before the standing lessons).
# Their churn is intended, and a report mostly made of intended churn is one you learn to skim.
VOLATILE_SECTION = "### User State"
VOLATILE_PARA = "**State ("
KEEP = 30


def durable_lines(text: str) -> list[str]:
    """Every non-blank line outside the nightly-rewritten parts, so their churn cannot mask a loss."""
    out, in_section, in_para = [], False, False
    for line in text.splitlines():
        if line.startswith("### "):
            in_section = line.strip() == VOLATILE_SECTION
        if line.startswith(VOLATILE_PARA):
            in_para = True
        elif in_para and line.strip() == "---":
            in_para = False
        if not in_section and not in_para and line.strip():
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
