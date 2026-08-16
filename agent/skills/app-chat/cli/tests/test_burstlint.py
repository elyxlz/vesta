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

NOW = dt.datetime(2026, 1, 2, 18, 0, tzinfo=dt.UTC)


def rows(*specs: tuple[int, str]) -> list[tuple[str, str]]:
    """Build DESCENDING rows from (minutes_before_NOW, type) pairs."""
    out = [((NOW - dt.timedelta(minutes=m)).isoformat(), k) for m, k in specs]
    return sorted(out, key=lambda r: r[0], reverse=True)


def burst(*specs: tuple[int, str]) -> int:
    return burst_length(rows(*specs), now=NOW)


def write_db(path, specs: list[tuple[int, str]]) -> None:
    """Write rows OLDEST FIRST, because id is the append order of a real store.

    The burst walk reads `ORDER BY id DESC`, id being the only ordering that does not depend on
    every row spelling its timestamp the same way. A fixture that inserts out of chronological
    order therefore describes a store that cannot exist, and any verdict it produces is about
    nothing."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, data TEXT)")
    for minutes, kind in sorted(specs, key=lambda s: -s[0]):
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


@pytest.mark.parametrize("specs,expected", [(UNDER, BURST_MAX - 1), (AT, BURST_MAX)])
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
        [(1, "chat"), (2, "chat"), (3, "user")] + [(i, "chat") for i in range(4, 4 + BURST_MAX)],
    )
    assert burst_lint_reason(db, now=NOW) == ""


def test_a_full_burst_after_a_reply_still_blocks(tmp_path):
    """A reply raises the ceiling; it does not remove it.

    The first version of this put the reply older than the twelve sends AND older than an earlier
    run, so it was indistinguishable from `test_at_the_threshold_blocks` and the reply could not
    affect the verdict either way. It has to be a full burst, then a reply, then a full burst."""
    db = tmp_path / "after_reply.db"
    write_db(
        db,
        [(i, "chat") for i in range(BURST_MAX + 2, BURST_MAX * 2 + 2)]
        + [(BURST_MAX + 1, "user")]
        + [(i, "chat") for i in range(1, BURST_MAX + 1)],
    )
    assert burst_lint_reason(db, now=NOW)


@pytest.mark.parametrize("spelling", ["+01:00", "Z", "naive"])
def test_a_reply_is_seen_whatever_its_timestamp_spelling(tmp_path, spelling):
    """The ordering must not depend on every row spelling ISO-8601 the same way.

    A `+01:00` offset naming a past instant sorts ABOVE a `+00:00` now as text, and `Z` sorts
    above a fractional second. Ordering the walk by that text put a reply at the head of the
    scan and ended a burst that had in fact continued past it."""
    reply_at = NOW - dt.timedelta(minutes=BURST_MAX + 1)
    if spelling == "+01:00":
        stamp = reply_at.astimezone(dt.timezone(dt.timedelta(hours=1))).isoformat()
    elif spelling == "Z":
        stamp = reply_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        stamp = reply_at.replace(tzinfo=None).isoformat()

    db = tmp_path / f"spelling_{spelling.replace(':', '')}.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, data TEXT)")
    conn.execute("INSERT INTO events (ts, data) VALUES (?, ?)", (stamp, json.dumps({"type": "user"})))
    for i in range(BURST_MAX, 0, -1):
        ts = (NOW - dt.timedelta(minutes=i)).isoformat()
        conn.execute("INSERT INTO events (ts, data) VALUES (?, ?)", (ts, json.dumps({"type": "chat"})))
    conn.commit()
    conn.close()
    assert burst_lint_reason(db, now=NOW), f"a {spelling} reply misordered the walk"


@pytest.mark.parametrize("payload", ["null", "5", '"text"', '{"type":["user"]}', '{"type":{}}'])
def test_valid_json_that_is_not_an_object_allows(tmp_path, payload):
    """These are valid JSON and none of them has `.get`, or is hashable.

    Left unguarded they raised straight out of `app-chat send`: no message, no reason, no hint
    that --burst exists. A crash is strictly worse than a block."""
    db = tmp_path / f"payload_{abs(hash(payload))}.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, data TEXT)")
    for i in range(BURST_MAX, 0, -1):
        conn.execute(
            "INSERT INTO events (ts, data) VALUES (?, ?)",
            ((NOW - dt.timedelta(minutes=i)).isoformat(), payload),
        )
    conn.commit()
    conn.close()
    assert burst_lint_reason(db, now=NOW) == ""


def test_an_undateable_user_reply_still_ends_the_burst(tmp_path):
    """A user row ends the burst for BEING a user row.

    Deciding that from the timestamp first meant an unparseable reply was skipped entirely: it
    neither ended the burst nor advanced the trail, so the walk ran on into the previous burst
    and blocked after eleven sends."""
    db = tmp_path / "undateable.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, data TEXT)")
    for i in range(BURST_MAX * 2, BURST_MAX, -1):
        conn.execute("INSERT INTO events (ts, data) VALUES (?, ?)", ((NOW - dt.timedelta(minutes=i)).isoformat(), json.dumps({"type": "chat"})))
    conn.execute(
        "INSERT INTO events (ts, data) VALUES (?, ?)", ((NOW - dt.timedelta(minutes=BURST_MAX)).isoformat() + " ", json.dumps({"type": "user"}))
    )
    for i in range(BURST_MAX - 1, 0, -1):
        conn.execute("INSERT INTO events (ts, data) VALUES (?, ?)", ((NOW - dt.timedelta(minutes=i)).isoformat(), json.dumps({"type": "chat"})))
    conn.commit()
    conn.close()
    assert burst_lint_reason(db, now=NOW) == ""


def test_unknown_event_types_do_not_bridge_a_cold_burst(tmp_path):
    """Any non-conversation row arriving on a timer must not resurrect a dead burst.

    Letting an unrecognised type advance the trail means a typing indicator, a tool event or a
    delivery receipt silently disables the gap clause, which is the one failure that would gag a
    genuinely urgent message the next morning."""
    db = tmp_path / "bridged.db"
    write_db(
        db,
        [(480 + i, "chat") for i in range(BURST_MAX)] + [(i * 5, "tool") for i in range(1, 96)],
    )
    assert burst_lint_reason(db, now=NOW) == ""


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
