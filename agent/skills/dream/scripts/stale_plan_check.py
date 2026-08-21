#!/usr/bin/env python3
"""Flag a STAGED PLAN that the last dream never reconciled with what that dream decided.

WHAT IT CHECKS. `~/agent/data/drafts/` holds plans staged for a named day, with the date in the
filename (`brief_2026-04-14.md`, `plan-2026-04-14.md`, `2026-04-14.md`). This reports every such
plan that is still pointed at today or a later day and whose last write predates the newest summary
in `~/agent/dreamer/`.

WHY THAT CLASS. The dream is the most recent complete pass over the user's state, so a plan written
before it and still aimed at a day that has not happened predates its conclusions, whether or not
the words happen to clash. That is mechanical and checkable, unlike "two files disagree". It matters
because a dated plan is the most specific artifact in the room: it gets read as the operative one
and beats the general note that supersedes it, even when that note is in context the whole time.

WHAT IT DOES NOT DO. It does not read the plan, compare wording, or guess intent. It reports that a
plan was staged before the night that superseded it and leaves the judgement to the reader. A
checker that tried to decide which of two notes is right would be wrong often enough to get ignored.

Exit 0 when clean, or when there is no dream summary to compare against; exit 1 when something needs
reconciling. `--self-test` runs both directions over a synthetic tree.
"""

from __future__ import annotations

import datetime as dt
import os
import pathlib as pl
import re
import sys
import tempfile

HOME = pl.Path.home()
DRAFTS = HOME / "agent" / "data" / "drafts"
DREAMER = HOME / "agent" / "dreamer"

# Dream summaries are named YYYY-MM-DDTHHMM.md. Anything else in dreamer/ is a working note.
SUMMARY = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})\.md$")

# A staged plan names the day it is for, anywhere in its filename.
DATED = re.compile(r"(\d{4}-\d{2}-\d{2})")


def latest_dream(dreamer_dir: pl.Path) -> tuple[dt.datetime, pl.Path] | None:
    """The most recent dream summary, by the timestamp in its NAME rather than its mtime.

    The name is the honest source: a summary edited later still describes the night it was written,
    and mtime would silently move every time a file is touched.
    """
    best: tuple[dt.datetime, pl.Path] | None = None
    if not dreamer_dir.is_dir():
        return None
    for path in dreamer_dir.iterdir():
        m = SUMMARY.match(path.name)
        if not m:
            continue
        when = dt.datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}", "%Y-%m-%d %H:%M")
        if best is None or when > best[0]:
            best = (when, path)
    return best


def stale_plans(
    drafts_dir: pl.Path,
    dream_at: dt.datetime,
    today: dt.date,
) -> list[tuple[pl.Path, dt.datetime, dt.date]]:
    """Staged plans for today or later whose last write predates the dream."""
    out: list[tuple[pl.Path, dt.datetime, dt.date]] = []
    if not drafts_dir.is_dir():
        return out
    for path in sorted(drafts_dir.iterdir()):
        if not path.is_file():
            continue
        m = DATED.search(path.name)
        if not m:
            continue
        try:
            for_day = dt.datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if for_day < today:
            continue  # a plan for a day already gone cannot mislead today's decision
        written = dt.datetime.fromtimestamp(path.stat().st_mtime)
        if written < dream_at:
            out.append((path, written, for_day))
    return out


def report(
    *,
    drafts_dir: pl.Path = DRAFTS,
    dreamer_dir: pl.Path = DREAMER,
    today: dt.date | None = None,
) -> tuple[int, str]:
    """Return (exit_code, text). Non-zero means something needs reconciling."""
    today = today or dt.date.today()
    latest = latest_dream(dreamer_dir)
    if latest is None:
        return 0, "stale_plan_check: no dream summary found, nothing to compare against"
    dream_at, dream_path = latest
    hits = stale_plans(drafts_dir, dream_at, today)
    if not hits:
        return 0, (
            f"stale_plan_check: clean. Newest dream {dream_path.name} "
            f"({dream_at:%Y-%m-%d %H:%M}); no plan staged for today or later predates it."
        )
    lines = [
        f"stale_plan_check: {len(hits)} staged plan(s) NOT reconciled with {dream_path.name} ({dream_at:%Y-%m-%d %H:%M}).",
        "",
        "Each of these was written BEFORE the night that superseded it and is still pointed at a",
        "day that has not happened, so it predates that night's conclusions.",
        "",
    ]
    for path, written, for_day in hits:
        lines.append(f"  {path}")
        lines.append(f"      staged {written:%Y-%m-%d %H:%M}, for {for_day}, dream was {dream_at:%H:%M}")
    lines += [
        "",
        "Re-read each against tonight's decisions and either update it or delete it. Do not leave it",
        "on disk unchanged: a stale plan is read as the operative one precisely because it is the",
        "most specific thing in the room.",
    ]
    return 1, "\n".join(lines)


_DREAM_AT = dt.datetime(2026, 4, 14, 3, 46)
_TODAY = dt.date(2026, 4, 14)


def _seed(root: pl.Path) -> tuple[pl.Path, pl.Path, float]:
    """Build a synthetic tree. Returns (drafts, dreamer, an mtime later than the dream)."""
    drafts = root / "drafts"
    dreamer = root / "dreamer"
    drafts.mkdir()
    dreamer.mkdir()

    (dreamer / "2026-04-14T0346.md").write_text("dream")
    (dreamer / "2026-04-13T0402.md").write_text("older dream")
    (dreamer / "note-something-2026-03-02.md").write_text("a working note, not a summary")

    before = (_DREAM_AT - dt.timedelta(hours=5)).timestamp()
    after = (_DREAM_AT + dt.timedelta(hours=4)).timestamp()

    def stage(name: str, when: float) -> None:
        path = drafts / name
        path.write_text("plan")
        os.utime(path, (when, when))

    # RED: staged the evening before, for the day the dream ended on.
    stage("brief_2026-04-14.md", before)
    # RED: a plan for a later day, also written before the dream.
    stage("plan-2026-04-17.md", before)
    # GREEN: reconciled after the dream.
    stage("brief_2026-04-15.md", after)
    # GREEN: for a day already gone, so it cannot mislead today.
    stage("brief_2026-04-12.md", before)
    # GREEN: carries no date, so it is not a plan for a day.
    stage("scratch-notes.md", before)

    return drafts, dreamer, after


def _self_test() -> int:
    """Red and green over a synthetic tree.

    Reconciling a plan moves its mtime past the dream, so the same file that is red while it sits
    untouched is green once it has been dealt with; the control below asserts exactly that.
    """
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        root = pl.Path(tmp)
        drafts, dreamer, after = _seed(root)

        code, text = report(drafts_dir=drafts, dreamer_dir=dreamer, today=_TODAY)
        if code != 1:
            print(f"FAIL: expected exit 1 on the seeded tree, got {code}")
            bad += 1
        for want in ("brief_2026-04-14.md", "plan-2026-04-17.md"):
            if want not in text:
                print(f"FAIL: should have flagged {want}")
                bad += 1
        for unwanted in ("brief_2026-04-15.md", "brief_2026-04-12.md", "scratch-notes.md"):
            if unwanted in text:
                print(f"FAIL: should NOT have flagged {unwanted}")
                bad += 1
        # It must name the newest summary, not merely any of them.
        if "2026-04-14T0346.md" not in text:
            print("FAIL: did not anchor on the NEWEST dream summary")
            bad += 1

        # CONTROL: with every plan reconciled, it must go quiet. A checker that never returns
        # clean is a checker nobody reads.
        for path in drafts.iterdir():
            os.utime(path, (after, after))
        code, text = report(drafts_dir=drafts, dreamer_dir=dreamer, today=_TODAY)
        if code != 0:
            print(f"FAIL CONTROL: everything reconciled should exit 0, got {code}:\n{text}")
            bad += 1

        # CONTROL: no dream summaries at all must not crash or cry wolf.
        empty = root / "no-dreams"
        empty.mkdir()
        code, _ = report(drafts_dir=drafts, dreamer_dir=empty, today=_TODAY)
        if code != 0:
            print(f"FAIL CONTROL: absent dreamer dir should exit 0, got {code}")
            bad += 1

    if bad:
        print(f"stale_plan_check: self-test FAILED, {bad} wrong")
        return 1
    print("stale_plan_check: self-test clean (2 must-flag, 3 must-not, 2 controls)")
    return 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    code, text = report()
    print(text)
    sys.exit(code)


if __name__ == "__main__":
    main()
