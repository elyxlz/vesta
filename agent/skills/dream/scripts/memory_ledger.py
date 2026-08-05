#!/usr/bin/env python3
"""Report rules that vanished from MEMORY.md between nightly curations.

Curation rewrites MEMORY.md in place: without a ledger the loop silently deletes its own output,
and every later retrospective grades a set that has quietly shrunk. `--snapshot` checkpoints
everything the day changed (`git add -A`) in one commit whose subject opens with a fixed prefix
plus the box-local date, with a required `--summary` as the body; the report finds the newest such
commit by the prefix and diffs its MEMORY.md against the working file, so one report spans the
day's edits plus the curation that just ran, other commits (a sync checkpoint) never move the
baseline, and every removed line stays recoverable from git history.

Curation also rewords and consolidates constantly, so a raw line diff reports mostly rewrites, and
a report you learn to skim is worth nothing. Every departed line is matched against the lines that
arrived with it: one that mostly reappears is a rewrite and is listed for a glance, one that does
not is a loss and is what the report exists to make impossible to miss.

`### User State` and the Self `**State**:` paragraph are excluded: the dream skill orders both
rewritten wholesale every night. Everything else in MEMORY.md is meant to be durable.

    memory_ledger.py            report what left since the last checkpoint; run after curating
    memory_ledger.py --snapshot --summary '<one or two sentences>'   checkpoint the day; run last
"""

import datetime as dt
import difflib
import pathlib as pl
import re
import subprocess
import sys

REPO = pl.Path("~").expanduser()
REL = "agent/MEMORY.md"
MEMORY = pl.Path("~/agent/MEMORY.md").expanduser()
# The fixed, greppable start of every checkpoint subject; the box-local date is appended after it,
# so the baseline lookup matches on the prefix alone.
SNAPSHOT_PREFIX = "dream: nightly checkpoint"
VOLATILE_SECTION = "### User State"
# The nightly-rewritten Self line, `**State**: ...`, tolerating a dated variant `**State (5 Aug)**:`.
STATE_LINE = re.compile(r"^\*\*State(?: \([^)]*\))?\*\*:")
HEADING = re.compile(r"^#{1,6} ")
WORD = re.compile(r"[a-z]{4,}")
# A departed line scoring this or better against some arriving line is a rewrite of it. Character
# similarity catches an edited line, word overlap catches one folded into a longer line, and the
# match is always printed, so a wrong call here degrades to a vaguer warning rather than a silence.
REWRITE = 0.6


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
    """Split the departed lines into (rewritten, with what replaced them) and (lost). Departure is
    membership, not position: curation reorders constantly, and a positional diff calls a moved line
    departed and re-arrived, pairing it with itself and burying the real losses under that noise."""
    before_set, after_set = set(before), set(after)
    gone = [line for line in before if line not in after_set]
    added = [line for line in after if line not in before_set]
    rewritten, lost = [], []
    for line in gone:
        match, score = best_match(line, added)
        if score >= REWRITE:
            rewritten.append((line, match))
        else:
            lost.append(line)
    return rewritten, lost


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False)


def snapshot(summary: str) -> int:
    """Checkpoint everything the day changed in one commit, subject `<prefix> (<date>)` with the
    caller's summary as the body: the box's nightly checkpoint, and the baseline the next report
    reads MEMORY.md out of. A merge in progress is never checkpointed (finishing it is the sync
    flow's job), and a clean tree has nothing to record: both skip quietly and the next report
    simply spans the extra day."""
    if _git("rev-parse", "-q", "--verify", "MERGE_HEAD").returncode == 0:
        print("snapshot skipped: merge in progress; the next report spans the extra day")
        return 0
    added = _git("add", "-A")
    if added.returncode != 0:
        print(added.stderr.strip(), file=sys.stderr)
        return 1
    if _git("diff", "--cached", "--quiet").returncode == 0:
        print("snapshot skipped: nothing changed since the last commit")
        return 0
    subject = f"{SNAPSHOT_PREFIX} ({dt.date.today().isoformat()})"
    committed = _git("commit", "-m", subject, "-m", summary)
    if committed.returncode != 0:
        print(committed.stderr.strip() or committed.stdout.strip(), file=sys.stderr)
        return 1
    print(f"snapshot committed: {subject}")
    return 0


def report() -> int:
    found = _git("log", "-n1", "--format=%H", "--grep", f"^{SNAPSHOT_PREFIX}")
    if found.returncode != 0:
        print(found.stderr.strip(), file=sys.stderr)
        return 1
    sha = found.stdout.strip()
    if not sha:
        print("no checkpoint commit yet; run --snapshot to start the ledger")
        return 0
    shown = _git("show", f"{sha}:{REL}")
    baseline = shown.stdout if shown.returncode == 0 else ""  # a baseline predating the file is empty
    rewritten, lost = classify(durable_lines(baseline), durable_lines(MEMORY.read_text()))
    print(f"vs {sha[:12]}: {len(lost)} durable line(s) lost, {len(rewritten)} reworded")
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


def main() -> int:
    args = sys.argv[1:]
    if not args:
        return report()
    if args[:2] != ["--snapshot", "--summary"] or len(args) != 3 or not args[2].strip():
        print("usage: memory_ledger.py [--snapshot --summary '<one or two sentences>']", file=sys.stderr)
        return 1
    return snapshot(args[2].strip())


if __name__ == "__main__":
    sys.exit(main())
