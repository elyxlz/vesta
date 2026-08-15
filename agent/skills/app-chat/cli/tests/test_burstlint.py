"""Tests for the burst lint.

Two properties are worth stating up front, because they are what the assertions
are actually protecting:

1. Every behaviour is tested in BOTH directions. A guard that only ever passes
   is indistinguishable from a guard that cannot fire, so each rule below has a
   case that must allow and a case that must block.

2. The cases are enumerated from what the module promises (what ends a burst,
   which error paths must allow), not from the branches the implementation
   happens to contain. The defects this class of code actually ships are
   omissions, and a test derived from the code cannot see a branch that was
   never written.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3

import pytest

from app_chat_cli.burstlint import (
    BURST_GAP_MINUTES,
    BURST_MAX,
    burst_length,
    burst_lint_reason,
)

NOW = dt.datetime(2026, 1, 2, 18, 0, tzinfo=dt.timezone.utc)


def rows(*specs: tuple[int, str]) -> list[tuple[str, str]]:
    """Build DESCENDING rows from (minutes_before_NOW, type) pairs."""
    out = [((NOW - dt.timedelta(minutes=m)).isoformat(), k) for m, k in specs]
    return sorted(out, key=lambda r: r[0], reverse=True)


def burst(*specs: tuple[int, str]) -> int:
    return burst_length(rows(*specs), now=NOW)


def write_db(path, specs: list[tuple[int, str]]) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, data TEXT)")
    for minutes, kind in specs:
        ts = (NOW - dt.timedelta(minutes=minutes)).isoformat()
        conn.execute(
            "INSERT INTO events (ts, data) VALUES (?, ?)",
            (ts, json.dumps({"type": kind, "ts": ts, "text": "x"})),
        )
    conn.commit()
    conn.close()


UNDER = [(i, "chat") for i in range(1, BURST_MAX)]
AT = [(i, "chat") for i in range(1, BURST_MAX + 1)]


# --- counting -------------------------------------------------------------


def test_no_events_counts_zero():
    assert burst() == 0


def test_consecutive_sends_are_counted():
    assert burst((1, "chat"), (2, "chat"), (3, "chat")) == 3


@pytest.mark.parametrize(
    "specs,expected", [(UNDER, BURST_MAX - 1), (AT, BURST_MAX)]
)
def test_counts_are_exact_at_the_threshold(specs, expected):
    assert burst(*specs) == expected


# --- what ends a burst ----------------------------------------------------


def test_a_user_message_ends_the_burst():
    assert burst((1, "chat"), (2, "chat"), (3, "user"), (4, "chat"), (5, "chat")) == 2


def test_a_user_message_as_the_newest_event_yields_zero():
    assert burst((1, "user"), (2, "chat"), (3, "chat")) == 0


def test_a_burst_that_went_cold_counts_zero():
    """The safety-critical case: yesterday's run must not gag today's message."""
    assert burst(*[(i, "chat") for i in range(600, 600 + BURST_MAX * 2)]) == 0


def test_a_gap_splits_the_burst():
    assert (
        burst(
            (1, "chat"),
            (2, "chat"),
            (BURST_GAP_MINUTES + 40, "chat"),
            (BURST_GAP_MINUTES + 41, "chat"),
        )
        == 2
    )


def test_the_gap_boundary_is_inclusive():
    assert burst((1, "chat"), (1 + BURST_GAP_MINUTES, "chat")) == 2
    assert burst((1, "chat"), (2 + BURST_GAP_MINUTES, "chat")) == 1


# --- malformed input ------------------------------------------------------


def test_an_unparseable_timestamp_is_skipped():
    assert burst_length([("not-a-date", "chat")], now=NOW) == 0


def test_an_unknown_event_type_neither_counts_nor_stops():
    assert burst((1, "chat"), (2, "system"), (3, "chat")) == 2


def test_a_naive_timestamp_does_not_raise():
    naive = NOW.replace(tzinfo=None).isoformat()
    assert burst_length([(naive, "chat")], now=NOW) == 1


# --- the verdict, against a real database ---------------------------------


def test_under_the_threshold_allows(tmp_path):
    db = tmp_path / "quiet.db"
    write_db(db, UNDER)
    assert burst_lint_reason(db, now=NOW) == ""


def test_at_the_threshold_blocks(tmp_path):
    db = tmp_path / "loud.db"
    write_db(db, AT)
    reason = burst_lint_reason(db, now=NOW)
    assert reason
    assert str(BURST_MAX) in reason
    assert "--burst" in reason


def test_a_reply_resets_the_count(tmp_path):
    db = tmp_path / "answered.db"
    write_db(
        db,
        [(1, "chat"), (2, "chat"), (3, "user")]
        + [(i, "chat") for i in range(4, 4 + BURST_MAX)],
    )
    assert burst_lint_reason(db, now=NOW) == ""


def test_a_full_burst_after_a_reply_still_blocks(tmp_path):
    """A reply raises the ceiling; it does not remove it."""
    db = tmp_path / "after_reply.db"
    write_db(db, AT + [(BURST_MAX + 1, "user")])
    assert burst_lint_reason(db, now=NOW)


def test_a_cold_burst_allows(tmp_path):
    db = tmp_path / "stale.db"
    write_db(db, [(i, "chat") for i in range(600, 600 + BURST_MAX * 2)])
    assert burst_lint_reason(db, now=NOW) == ""


def test_events_newer_than_now_are_excluded(tmp_path):
    """Without a ts <= now bound, a question about one instant is answered
    about whichever burst ran most recently."""
    db = tmp_path / "wrong_object.db"
    write_db(db, [(-240, "chat")] * BURST_MAX + [(1, "chat"), (2, "chat")])
    assert burst_lint_reason(db, now=NOW) == ""


# --- error paths must allow, never silence a real message -----------------


def test_a_missing_database_allows(tmp_path):
    assert burst_lint_reason(tmp_path / "nope.db", now=NOW) == ""


def test_a_corrupt_database_allows(tmp_path):
    db = tmp_path / "corrupt.db"
    db.write_bytes(b"this is not a database")
    assert burst_lint_reason(db, now=NOW) == ""


def test_a_database_without_the_events_table_allows(tmp_path):
    db = tmp_path / "noschema.db"
    sqlite3.connect(db).execute("CREATE TABLE other (x TEXT)")
    assert burst_lint_reason(db, now=NOW) == ""


def test_unparseable_event_payloads_allow(tmp_path):
    db = tmp_path / "badjson.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, data TEXT)")
    for i in range(1, BURST_MAX + 1):
        conn.execute(
            "INSERT INTO events (ts, data) VALUES (?, ?)",
            ((NOW - dt.timedelta(minutes=i)).isoformat(), "{not json"),
        )
    conn.commit()
    conn.close()
    assert burst_lint_reason(db, now=NOW) == ""
