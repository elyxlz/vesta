#!/usr/bin/env python3
"""Report rules that vanished from MEMORY.md between nightly curations.

Curation rewrites MEMORY.md in place and the file is committed only occasionally, so a rule
written one night and compressed away the next leaves no trace in git or anywhere else. This keeps
its own dated snapshots and diffs against the most recent one, taken at the end of the previous
dream, so one report spans the day's edits plus the curation that just ran.

Curation also rewords and consolidates constantly, so a raw line diff reports mostly rewrites, and
a report you learn to skim is worth nothing. Every departed line is matched against the lines that
arrived with it: one that mostly reappears is a rewrite and is listed for a glance, one that does
not is a loss and is what the report exists to make impossible to miss.

`### User State` and the Self `**State**:` paragraph are excluded: the dream skill orders both
rewritten wholesale every night. Everything else in MEMORY.md is meant to be durable.

    memory_ledger.py            report what left since the last snapshot; run after curating
    memory_ledger.py --snapshot record the curated MEMORY.md as the new baseline; run last
"""

import datetime as dt
import difflib
import pathlib as pl
import re
import sys

MEMORY = pl.Path("~/agent/MEMORY.md").expanduser()
SNAPS = pl.Path("~/agent/data/memory-snapshots").expanduser()
VOLATILE_SECTION = "### User State"
# The nightly-rewritten Self line, `**State**: ...`, tolerating a dated variant `**State (5 Aug)**:`.
STATE_LINE = re.compile(r"^\*\*State(?: \([^)]*\))?\*\*:")
HEADING = re.compile(r"^#{1,6} ")
WORD = re.compile(r"[a-z]{4,}")
# A departed line scoring this or better against some arriving line is a rewrite of it. Character
# similarity catches an edited line, word overlap catches one folded into a longer line, and the
# match is always printed, so a wrong call here degrades to a vaguer warning rather than a silence.
REWRITE = 0.6
KEEP = 30


def durable_lines(text: str) -> list[str]:
    """Every non-blank line outside the nightly-rewritten parts, so their churn cannot mask a loss.
    The State paragraph ends at the first blank line or heading, so it can never swallow the rest
    of the file."""
    out, in_section, in_para = [], False, False
    for line in text.splitlines():
        if HEADING.match(line):
            in_section, in_para = line.strip() == VOLATILE_SECTION, False
        elif not line.strip():
            in_para = False
        elif STATE_LINE.match(line):
            in_para = True
        if not in_section and not in_para and line.strip():
            out.append(line.rstrip())
    return out


def best_match(gone: str, added: list[str]) -> tuple[str, float]:
    """The arriving line a departed one most resembles, and how strongly, on the better of two reads."""
    words = set(WORD.findall(gone.lower()))
    best, score = "", 0.0
    for cand in added:
        overlap = len(words & set(WORD.findall(cand.lower()))) / len(words) if words else 0.0
        combined = max(difflib.SequenceMatcher(None, gone, cand).ratio(), overlap)
        if combined > score:
            best, score = cand, combined
    return best, score


def classify(before: list[str], after: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """Split the departed lines into (rewritten, with what replaced them) and (lost)."""
    diff = list(difflib.ndiff(before, after))
    gone = [ln[2:] for ln in diff if ln.startswith("- ")]
    added = [ln[2:] for ln in diff if ln.startswith("+ ")]
    rewritten, lost = [], []
    for line in gone:
        match, score = best_match(line, added)
        if score >= REWRITE:
            rewritten.append((line, match))
        else:
            lost.append(line)
    return rewritten, lost


def latest_snapshot() -> pl.Path | None:
    return max(SNAPS.glob("*.md"), default=None)


def snapshot() -> int:
    SNAPS.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d")
    (SNAPS / f"{stamp}.md").write_text(MEMORY.read_text())
    for old in sorted(SNAPS.glob("*.md"))[:-KEEP]:
        old.unlink()
    print(f"snapshot saved: {stamp}.md ({len(list(SNAPS.glob('*.md')))} kept)")
    return 0


def report() -> int:
    prev = latest_snapshot()
    if prev is None:
        print("no prior snapshot; run --snapshot to start the ledger")
        return 0
    rewritten, lost = classify(durable_lines(prev.read_text()), durable_lines(MEMORY.read_text()))
    print(f"vs {prev.name}: {len(lost)} durable line(s) lost, {len(rewritten)} reworded")
    if rewritten:
        print("\nReworded, no answer needed, read only to check the meaning survived:\n")
        for line, match in rewritten:
            print(f"  ~ {line}\n    -> {match}")
    if lost:
        print("\nLost. Each needs an answer: which skill file it graduated into (say which), or why")
        print("it expired. Anything else is the loop deleting its own output.\n")
        for line in lost:
            print(f"  - {line}")
    return 0


if __name__ == "__main__":
    sys.exit(snapshot() if "--snapshot" in sys.argv[1:] else report())
