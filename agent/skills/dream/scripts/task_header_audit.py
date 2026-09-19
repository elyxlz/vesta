#!/usr/bin/env python3
"""Flag LIVE tasks whose metadata file is long enough to hand a reader a superseded fact first.

WHY THIS EXISTS (built 12 Aug 2026, third instance of the class in two days).

Task metadata here is append-only by design, which is right: the history is the evidence. The
failure mode is that the OLDEST facts sit at the TOP, so anyone reading top-down under time
pressure meets a superseded number before its correction.

  * 11 Aug, task `00e61586`: the HSBC chargeback file gave the wrong phone number first, with the
    correction twenty lines below it. He is abroad; the number he needs is the from-abroad line.
  * 12 Aug, task `177cde6d`: the EU261 file says `GBP 534.92` at lines 10, 14 and 18 as "the
    claim". The settled figure, `GBP 323.12`, is derived at line 249 of 448. Filing 534.92 is
    double recovery and hands Ryanair the refusal. **This one was mine to action the same day.**
  * The same shape in `maddy.md`, which contradicted itself three ways on nationality.

A rule ("write a header") already failed twice, so this is the mechanism instead.

**18 Sep 2026: measured WHO generates the backlog, and it is me, on the days I am being careful.**
Of roughly ten task-file appends made that day, the five where I appended a dated section WITHOUT
touching the top header all appeared in this audit's output hours later (`3a40da15`, `431f1cec`,
`71535f85`, `dc810aee`, `f340feab`); the ones where I also rewrote the header did not. A clean
natural experiment, unintended. The count went 13 -> 8 once I cleaned up after myself, and the
remaining 8 are older.

So this instrument measures a rate, not a stock: it fills up again every day I do good work on task
files. **The fix is not a better detector, it is updating the header in the same edit as the append**,
which is now a WHEN-rule in MEMORY. This audit stays as the backstop that catches the days I forget.

WHAT IT FLAGS, deliberately narrow so it stays worth reading:

    task status is PENDING  +  metadata >= MIN_LINES  +  no current-state block in the first 25

Dormant tasks are excluded on purpose. A 1,299-line file on something nobody will touch this month
is not a hazard, and flagging all 28 long files would make this report noise, which is how a check
gets ignored. Only a task that could be acted on can hand you the wrong number at the wrong moment.

FIX for anything it names: prepend a block with the settled figures, the next action, and any
near-miss trap, then leave the history below it untouched.

HONEST LIMIT, recorded the same morning it was built rather than after it misleads someone. This
checks SHAPE, never staleness: "long, and no current-state block near the top". It cannot read
whether the top is actually wrong. On 12 Aug it flagged `bf41e37f`, whose opening section turned out
to be accurate and current, naming the inbound-only booking state and the London anchor. That is a
correct flag by its own rule and a false alarm in substance. So treat a hit as "go LOOK at the top
of this file", never as "this file is wrong", and clear it by reading rather than by reflexively
prepending a header nobody needed.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

MIN_LINES = 120
HEAD_LINES = 25
HEADER_RE = re.compile(
    r"read this|current state|settled|status now|state now|top block|first block|tl;dr|summary|\bstatus:",
    re.IGNORECASE,
)


def pending_tasks() -> list[dict]:
    p = subprocess.run(["tasks", "list", "--json"], capture_output=True, text=True, timeout=120, check=False)
    if p.returncode != 0:
        print(f"tasks list FAILED rc={p.returncode}: {p.stderr[:200]}")
        raise SystemExit(2)
    rows = json.loads(p.stdout or "[]")
    rows = rows if isinstance(rows, list) else rows.get("tasks", [])
    return [r for r in rows if r.get("status") == "pending"]


def files_for(task_id: str) -> list[str]:
    """Every metadata file for a task: `<id>.md` plus any `<id>_suffix.md` companions."""
    return sorted(str(p) for p in Path("/root/.tasks/metadata").glob(f"{task_id}*.md"))


def has_header(lines: list[str]) -> bool:
    """True only if a current-state marker appears in a HEADING or a bolded status line.

    The first version searched the raw first 25 lines, so ANY prose containing one of those words
    disabled the check for that file. An adversarial pass on 13 Aug found three live files wrongly
    cleared that way: `544845ac` on a FILENAME (`audiogen_acquirers_summary.md`), `cc946367` on a
    sentence ending "not from a summary.", and `8d0f147a`, 762 lines, on the word "summary" inside a
    prose status line. A check that any stray word can switch off is not a check.
    """
    for line in lines[:HEAD_LINES]:
        s = line.strip()
        # `> **...**` is the HOUSE STYLE for these blocks and was invisible here until 19 Aug 2026,
        # when three files carrying an explicit "IS THE CURRENT STATE" block on line 1 were still
        # flagged. A check that cannot recognise the very fix it asks for teaches you to ignore it.
        if s.startswith(">"):
            s = s.lstrip("> ").strip()
        if not s.startswith(("#", "**", "| **")):
            continue
        if HEADER_RE.search(s):
            return True
    return False


# A HEADER THAT IS ITSELF STALE, added 11 Sep 2026. `has_header` asks only whether a marker exists,
# so a file passes FOREVER once anyone adds one, no matter how far the truth below has moved past
# it. That is not hypothetical: on 10 Sep `26f80e3a` opened with a dated 9 Sep block reading "I
# cannot do it: there is still no Stable credential in Keeper" while the bottom of the same file
# recorded the job DONE that morning. A reader landing on the top gets a confident falsehood and
# never reaches the correction. A stale header is worse than no header, because it also silences
# this check. So: find the newest date in the header region and the newest date in the whole file,
# and flag when the body has moved on by more than a day.
DATE_RE = re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", re.IGNORECASE)
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
# ZERO, not one. The first draft used 1 and then FAILED its own founding case: `26f80e3a` carried a
# 9 Sep header over a 10 Sep correction, a one-day gap, which is both the commonest shape and the
# dangerous one. Any body date LATER than the header date means the top no longer speaks for the
# file. Same-day appends are still ignored, which is all the tolerance this needs.
STALE_HEADER_DAYS = 0


def _dates(text: str) -> list[tuple[int, int]]:
    """(month, day) pairs found in the text. Year is deliberately ignored: these files span weeks,
    not years, and a missing year is far commoner here than a genuine year boundary."""
    return [(_MONTHS[m.group(2)[:3].lower()], int(m.group(1))) for m in DATE_RE.finditer(text)]


def _authorship_dates(text: str) -> list[tuple[int, int]]:
    """Dates that plausibly mark WHEN SOMEONE WROTE, as opposed to dates merely discussed in prose.

    FOUNDING CASE, 19 Sep 2026. `f340feab` was given a correct 18 Sep header, and this check went on
    flagging it. The culprit is line 51: *"Then 5 Sep he flies, 7 Sep is his first day, 8 Sep is
    graduation, 13-19 Sep is Cancun."* Nineteen September was that day, so `19 Sep` passed the
    "not in the future" filter, outranked the 18 Sep header by one day, and the file looked
    permanently superseded. The previous night's summary had claimed that file cleaned; it was not,
    and the claim went unchallenged because the instrument and the claim disagreed silently.

    The docstring below already says future dates are not authorship dates. This is the same
    sentence one step further: **a date in the middle of a sentence is not an authorship date
    either, whenever it falls.** Discarding future dates fixed the half that happened to be easy to
    recognise.

    So count a date only where these files actually put one when they mean "written now": at the
    START of a line, after optional markdown furniture (`#`, `>`, `*`, `-`, `|`), or immediately
    followed by a clock time. Everything mid-sentence is discussion.
    """
    out: list[tuple[int, int]] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        # A STRUCTURAL line (markdown heading, blockquote, bold lead, table lead) is where these
        # files put "written now". Any date on such a line counts.
        # Mirror has_header_block()'s notion of a marker line EXACTLY, rather than inventing a
        # second one: strip a leading `>` then require `#`, `**` or `| **`. That distinction is the
        # whole fix. `> **17 Sep 18:15: ...**` is the house style for an append stamp, while
        # `> Then 5 Sep he flies, 13-19 Sep is Cancun.` is a quoted PARAGRAPH that merely opens with
        # the same character. Treating every `>` line as structural put the founding case straight
        # back, which the control caught within a minute.
        s_ = stripped.lstrip("> ").strip() if stripped.startswith(">") else stripped
        structural = s_.startswith(("#", "**", "| **"))
        if structural:
            found = list(DATE_RE.finditer(raw))
            if found:
                out.append((_MONTHS[found[0].group(2)[:3].lower()], int(found[0].group(1))))
                continue
        # On an ordinary prose line, only a date IMMEDIATELY followed by a clock time is an
        # authorship stamp ("Appended 16 Sep 21:40"). Everything else mid-sentence is discussion.
        for m in DATE_RE.finditer(raw):
            tail = raw[m.end() : m.end() + 14]
            if re.match(r"\s*(20\d\d)?[.,]?\s*\d{1,2}:\d{2}", tail):
                out.append((_MONTHS[m.group(2)[:3].lower()], int(m.group(1))))
                break
    return out


def header_superseded(lines: list[str]) -> bool:
    """FUTURE DATES ARE NOT AUTHORSHIP DATES, and the first draft of this got it wrong in a way that
    would have made the check noise within a week. It flagged `26f80e3a` twenty minutes after a
    correct 11 Sep header was written on it, because the body discusses a shred deadline of 19 Sep.
    A file that tracks any future deadline would look permanently superseded. So a date later than
    today cannot be evidence that someone appended to this file, and is discarded on both sides."""
    import datetime

    today = datetime.date.today()
    cutoff = (today.month, today.day)

    def authored(text: str) -> list[tuple[int, int]]:
        return [d for d in _authorship_dates(text) if d <= cutoff]

    head = authored("\n".join(lines[:HEAD_LINES]))
    body = authored("\n".join(lines[HEAD_LINES:]))
    if not head or not body:
        return False
    newest_head, newest_body = max(head), max(body)
    if newest_body <= newest_head:
        return False
    # crude day distance inside a month-pair ordering, enough to ignore same-day appends
    delta = (newest_body[0] - newest_head[0]) * 31 + (newest_body[1] - newest_head[1])
    return delta > STALE_HEADER_DAYS


def audit() -> list[tuple[str, str, int, str]]:
    out = []
    for t in pending_tasks():
        for path in files_for(str(t.get("id", ""))):
            try:
                lines = Path(path).read_text(errors="ignore").split("\n")
            except OSError:
                continue
            if len(lines) < MIN_LINES:
                continue
            if has_header(lines) and not header_superseded(lines):
                continue
            why = "header superseded by later content" if has_header(lines) else "no current-state block"
            out.append((str(t["id"])[:8], Path(path).name, len(lines), f"[{why}] " + str(t.get("subject", ""))[:70]))
    return sorted(out, key=lambda r: -r[2])


def self_test() -> int:
    """Controls BOTH ways on fixtures, because 'nothing flagged' and 'the check never ran' print
    the same thing. A long file WITHOUT a header must be caught; a long file WITH one, and a short
    file without one, must not be."""
    import tempfile

    fails = []
    with tempfile.TemporaryDirectory() as d:
        long_no_header = "\n".join(["some appended history line"] * (MIN_LINES + 10))
        long_with_header = "# READ THIS BLOCK FIRST\n" + long_no_header
        short_no_header = "\n".join(["short file"] * 10)

        cases = [
            ("long, no header", long_no_header, True),
            ("long, has header", long_with_header, False),
            ("short, no header", short_no_header, False),
        ]
        for label, body, want in cases:
            f = Path(d) / "x.md"
            f.write_text(body)
            lines = f.read_text().split("\n")
            got = len(lines) >= MIN_LINES and not HEADER_RE.search("\n".join(lines[:HEAD_LINES]))
            if got != want:
                fails.append(f"{'MISSED' if want else 'FALSE POSITIVE'}: {label}")

    # AUTHORSHIP-DATE fixtures, added 19 Sep 2026 with the founding case they come from. A prose
    # date range ("13-19 Sep is Cancun") must NOT count as someone appending, or every file that
    # mentions a date range outranks its own header the moment that range reaches today. And a real
    # marker line MUST still count, or the fix that silences the false positive silences the check.
    date_cases = [
        ("prose range in a blockquote", "> Then 5 Sep he flies, 13-19 Sep is Cancun.", 0),
        ("heading, date not first token", "# CURRENT STATE, 10 Sep 2026. old.", 1),
        ("blockquote bold marker (house style)", "> **17 Sep 18:15: corrected the queue**", 1),
        ("prose date followed by a clock time", "Appended on 16 Sep 21:40 after reading.", 1),
        ("prose date, no time", "the ballot closes 11 Oct and he should know.", 0),
    ]
    for label, text, want in date_cases:
        got = len(_authorship_dates(text))
        if got != want:
            fails.append(f"AUTHORSHIP DATE: {label}: wanted {want}, got {got}")

    # And both directions through the real predicate, not just the extractor.
    head_old = ["# CURRENT STATE, 10 Sep 2026. old.", ""] + [""] * 23
    head_new = ["# CURRENT STATE, 18 Sep 2026. fresh.", ""] + [""] * 23
    if not header_superseded([*head_old, "## 17 Sep 2026 09:00. newer."]):
        fails.append("CONTROL: a genuinely superseded header was NOT flagged")
    if header_superseded([*head_new, "> Then 13-19 Sep is Cancun, ballot 11 Oct."]):
        fails.append("FALSE POSITIVE: prose dates outranked a fresh header")

    # CONTROL on the live side: the task CLI must actually answer, or an empty report below would
    # mean "could not look", which reads identically to "nothing to fix".
    try:
        n = len(pending_tasks())
    except SystemExit:
        fails.append("could not read pending tasks at all")
        n = -1
    if n == 0:
        fails.append("CONTROL: zero pending tasks, so an empty audit proves nothing")

    for f in fails:
        print("  SELF-TEST:", f)
    print(
        f"task_header_audit: {'self-test clean' if not fails else 'SELF-TEST FAILED'} "
        f"(3 fixtures, controls both ways, {n} pending tasks readable)"
    )
    return 1 if fails else 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    rows = audit()
    if not rows:
        print(f"task_header_audit: every live task's metadata under {MIN_LINES} lines or already carrying a current-state block")
        return 0
    print(
        f"task_header_audit: {len(rows)} LIVE task file(s) long enough to hand a reader a "
        f"superseded fact first.\nTwo kinds: no current-state block at all, or one the body has since overtaken: GO LOOK at each top, then "
        f"either prepend a current-state block or\nclear it as already accurate. Leave the "
        f"history below untouched either way.\n"
    )
    for tid, name, n, subject in rows:
        print(f"  {n:5d} lines  {tid}  {name}")
        print(f"                 {subject}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
