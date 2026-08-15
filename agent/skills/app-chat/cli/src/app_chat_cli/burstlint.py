"""Burst lint: refuse a send when the agent is monologuing rather than talking.

The bubble lint enforces the SHAPE of a single send and is blind to volume. The
failure it cannot see is a long run of individually well-formed bubbles: an
answer, then a correction to it, then a correction to that, then the whole plan
re-sent. Every bubble passes on its own and the aggregate buries whichever one
mattered.

A burst is consecutive agent sends with no user message between them AND no gap
longer than ``BURST_GAP_MINUTES`` from one send to the next. Both clauses matter:

- The user writing back ends a burst, because that is a conversation. A reply
  raises the ceiling; it does not remove it, so a fresh run of a dozen sends
  after a reply is still a burst.
- A quiet gap ends a burst, because a message after silence is a new contact.

The gap clause is the safety-critical half. Without it the counter never clears,
and a guard meant to reduce noise ends up suppressing the next morning's first
message, when it may be the one thing the user actually needs. Every error path
returns "" (allow) for the same reason: a missing database, an unreadable row or
an unparseable timestamp must never be able to silence a real message. The guard
exists to stop noise, never to stop the agent from reaching the user.

The bypass is ``--burst``, for a genuine emergency (a deadline, a cancellation, a
broken service). ``--longform`` deliberately does not bypass it: reference
material is no more welcome in the thirteenth unanswered send than prose is.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib as pl
import sqlite3

# A real answer can run to several bubbles; a monologue runs to dozens.
BURST_MAX = 12

# Longer than the pause inside one multi-bubble answer, shorter than any real
# silence. Sends further apart than this belong to different contacts.
BURST_GAP_MINUTES = 30

AGENT_TYPES = {"chat"}
USER_TYPES = {"user"}


def _parse_ts(raw: object) -> dt.datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def burst_length(rows: list[tuple[str, str]], now: dt.datetime | None = None) -> int:
    """Count agent sends in the burst ending at ``now``.

    ``rows`` is [(ts, type), ...] in DESCENDING time order, newest first.

    Walks backwards from the newest event and stops at the first thing that ends
    a burst: a user message, or a gap wider than ``BURST_GAP_MINUTES`` between
    two adjacent events. ``now`` closes the burst at the near end, so a burst
    that went quiet an hour ago counts 0 rather than its historical length.
    """
    limit = dt.timedelta(minutes=BURST_GAP_MINUTES)
    count = 0
    newer: dt.datetime | None = now

    for raw_ts, raw_type in rows:
        ts = _parse_ts(raw_ts)
        if ts is None:
            continue
        if newer is not None and (newer - ts) > limit:
            break  # the trail went cold before this event: burst over
        if raw_type in USER_TYPES:
            break  # the user replied: a conversation, not a monologue
        if raw_type in AGENT_TYPES:
            count += 1
        newer = ts

    return count


def _load_rows(
    db_path: pl.Path, now: dt.datetime | None = None, limit: int = 200
) -> list[tuple[str, str]]:
    """The newest ``limit`` events at or before ``now``.

    The ``ts <= now`` bound is load-bearing: without it the walk starts from the
    newest row in the table, so asking whether a burst was running at some past
    instant is answered about whatever burst ran most recently. ISO-8601 UTC
    strings sort lexicographically in the same order as the instants they name,
    so comparing them as strings is correct here.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        if now is None:
            raw = conn.execute(
                "SELECT ts, data FROM events ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            raw = conn.execute(
                "SELECT ts, data FROM events WHERE ts <= ? ORDER BY ts DESC LIMIT ?",
                (now.isoformat(), limit),
            ).fetchall()
    finally:
        conn.close()

    rows: list[tuple[str, str]] = []
    for ts, data in raw:
        try:
            kind = json.loads(data).get("type", "")
        except (TypeError, ValueError):
            kind = ""
        rows.append((ts, kind))
    return rows


def burst_lint_reason(db_path: pl.Path | None = None, now: dt.datetime | None = None) -> str:
    """Return a non-empty explanation when this send would extend an over-long
    burst, or "" if it passes (including on any error: the guard fails open)."""
    path = db_path or (pl.Path.home() / ".app-chat" / "app-chat.db")
    moment = now or dt.datetime.now(dt.timezone.utc)
    try:
        if not path.exists():
            return ""
        rows = _load_rows(path, now=moment)
    except (sqlite3.Error, OSError):
        return ""

    sent = burst_length(rows, now=moment)
    if sent < BURST_MAX:
        return ""

    return (
        f"burst lint: {sent} sends in this burst with no reply from them. "
        f"you are not answering any more, and every extra bubble makes the ones that "
        f"mattered harder to find. stop here and wait. if something you already sent is "
        f"wrong, fix the ONE bubble that is wrong rather than re-sending the whole thing. "
        f"the counter clears on their next message or after {BURST_GAP_MINUTES} min of "
        f"quiet. real emergency only: --burst"
    )
