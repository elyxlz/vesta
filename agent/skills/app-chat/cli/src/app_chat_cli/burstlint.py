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
message, when it may be the one thing the user actually needs. Every failure path
returns "" (allow) for the same reason: a missing or corrupt database, a payload
that is not an object, a timestamp in an unexpected spelling, an event type
nobody anticipated. The catch around the walk is deliberately broad rather than a
list of the exceptions imagined at authoring time, because three unimagined ones
(``null``, ``5`` and ``{"type": []}`` are all valid JSON) crashed the send
outright, which is strictly worse than blocking: no message, no reason, and no
hint that the bypass exists. The guard exists to stop noise, never to stop the
agent from reaching the user.

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
        parsed = parsed.replace(tzinfo=dt.UTC)
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
        # A user row ends the burst on the strength of BEING a user row. Deciding that from the
        # timestamp first meant an undateable reply was skipped entirely: it neither ended the
        # burst nor advanced the trail, so the walk ran on into the PREVIOUS burst and blocked
        # after 11 sends. An unreadable row must never be able to silence a message, so the
        # cheap, always-available fact is the one that gets to stop the count.
        if isinstance(raw_type, str) and raw_type in USER_TYPES:
            break  # the user replied: a conversation, not a monologue

        ts = _parse_ts(raw_ts)
        if ts is None:
            continue
        if newer is not None and (newer - ts) > limit:
            break  # the trail went cold before this event: burst over
        if isinstance(raw_type, str) and raw_type in AGENT_TYPES:
            count += 1
            newer = ts
        # A row that is neither agent nor user does NOT advance the trail. Letting it advance
        # meant any unrelated event type (a typing indicator, a tool event, a delivery receipt)
        # arriving on a timer would bridge the gap check indefinitely and resurrect a burst that
        # went cold hours ago, which is the one failure this guard must never have.

    return count


def _load_rows(db_path: pl.Path, now: dt.datetime | None = None, limit: int = 200) -> list[tuple[str, str]]:
    """The newest ``limit`` events at or before ``now``.

    The ``at or before now`` bound is load-bearing: without it the walk starts from the newest
    row in the table, so asking whether a burst was running at some past instant is answered
    about whatever burst ran most recently.

    That bound is applied to PARSED INSTANTS, not to the raw strings. Doing it in SQL as a text
    comparison is correct for exactly one spelling of ISO-8601: an offset of ``+01:00`` naming an
    instant safely in the past sorts ABOVE a ``+00:00`` now, and a ``Z`` suffix sorts above a
    fractional second. Either drops a real user reply out of the window, and a dropped reply makes
    the guard BLOCK. The column is bare ``TEXT`` and ``store.append`` writes whatever the caller
    handed it, so nothing enforces a spelling.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        # Ordered by id, not by ts. id is the append order of an append-only store, so it is the
        # true chronology and needs no parsing. Ordering by the ts TEXT is what made a `+01:00`
        # reply sort above every `+00:00` row and land at the head of the walk, where it ended a
        # burst that had in fact continued for twelve sends after it.
        raw = conn.execute("SELECT ts, data FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()

    rows: list[tuple[str, str]] = []
    for ts, data in raw:
        if now is not None:
            parsed = _parse_ts(ts)
            if parsed is not None and parsed > now:
                continue
        try:
            payload = json.loads(data)
        except (TypeError, ValueError):
            payload = None
        # `null`, `5` and `"text"` are all valid JSON and none of them has `.get`. Calling it
        # raised AttributeError straight out of `app-chat send`, killing the message with a
        # traceback: strictly worse than blocking, because there is no reason given and no hint
        # that --burst exists. `{"type": ["user"]}` is valid too, and an unhashable set member.
        kind = payload.get("type", "") if isinstance(payload, dict) else ""
        if not isinstance(kind, str):
            kind = ""
        rows.append((ts, kind))
    return rows


def burst_lint_reason(db_path: pl.Path | None = None, now: dt.datetime | None = None) -> str:
    """Return a non-empty explanation when this send would extend an over-long
    burst, or "" if it passes (including on any error: the guard fails open)."""
    path = db_path or (pl.Path.home() / ".app-chat" / "app-chat.db")
    moment = now or dt.datetime.now(dt.UTC)
    try:
        if not path.exists():
            return ""
        rows = _load_rows(path, now=moment)
    except (sqlite3.Error, OSError):
        return ""

    try:
        sent = burst_length(rows, now=moment)
    except Exception:
        # The contract is that NOTHING here can gag a real message. A narrow except list is a
        # promise about the exceptions imagined at authoring time, and three unimagined ones
        # (valid-JSON-non-object payloads) crashed `app-chat send` with a traceback, which is
        # strictly worse than blocking: no message, no reason, no hint that --burst exists.
        return ""
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
