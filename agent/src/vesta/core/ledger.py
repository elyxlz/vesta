"""Processed-event ledger for idempotency tracking (Phases 2 & 3).

Phase 2 (observe-only): records every event_id entering the queue, marks
duplicates, never suppresses.

Phase 3 (suppression): filter_and_record() separates novel from duplicate
events before queuing.  Duplicate = same event_id that was previously
processed as novel (is_duplicate=0).  On any ledger error, fails open
so no legitimate event is ever lost.
"""

import datetime as dt
import hashlib
import json
import pathlib as pl
import sqlite3
import typing as tp

if tp.TYPE_CHECKING:
    import vesta.models as vm

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id          TEXT    NOT NULL,
    seen_at           TEXT    NOT NULL,
    invocation_id     TEXT,
    is_duplicate      INTEGER NOT NULL DEFAULT 0,
    source            TEXT,
    notification_type TEXT
);
CREATE INDEX IF NOT EXISTS idx_event_id ON events (event_id);
CREATE INDEX IF NOT EXISTS idx_seen_at  ON events (seen_at);
"""


def _open(db_path: pl.Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def _derive_event_id(notif: "vm.Notification") -> str:
    """Return the event_id from the notification, or a stable hash fallback."""
    data = notif.model_dump(exclude={"file_path"})
    eid = data.get("event_id")
    if eid:
        return str(eid)
    payload = json.dumps(data, sort_keys=True, default=str)
    return "fallback:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def record_events(
    notifications: "list[vm.Notification]",
    *,
    db_path: pl.Path,
    invocation_id: str | None,
) -> None:
    """Write ledger entries for a batch of notifications.

    Each entry is marked novel (is_duplicate=0) or duplicate (is_duplicate=1)
    based on whether the event_id has been seen before.  Never raises —
    this is observation-only and must never block the main execution path.
    """
    if not notifications:
        return
    try:
        conn = _open(db_path)
        now = dt.datetime.now().isoformat()
        for notif in notifications:
            eid = _derive_event_id(notif)
            row = conn.execute("SELECT 1 FROM events WHERE event_id = ?", (eid,)).fetchone()
            is_dup = 1 if row else 0
            conn.execute(
                "INSERT INTO events (event_id, seen_at, invocation_id, is_duplicate, source, notification_type) VALUES (?, ?, ?, ?, ?, ?)",
                (eid, now, invocation_id, is_dup, notif.source, notif.type),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass  # Ledger failure must never interrupt event processing


def filter_and_record(
    notifications: "list[vm.Notification]",
    *,
    db_path: pl.Path,
    invocation_id: str | None,
    suppress: bool,
) -> "tuple[list[vm.Notification], list[vm.Notification]]":
    """Split notifications into (novel, suppressed) and record all in ledger.

    An event is a duplicate if its event_id already appears in the ledger
    with is_duplicate=0, meaning it was previously processed as a novel event.

    When suppress=False (bypass mode) every notification is treated as novel —
    the split still runs and everything is recorded, but nothing is withheld.

    Fails open: on any ledger error returns (notifications, []) so the caller
    always processes everything rather than silently dropping events.
    """
    if not notifications:
        return [], []
    try:
        conn = _open(db_path)
        now = dt.datetime.now().isoformat()
        novel: list[vm.Notification] = []
        suppressed: list[vm.Notification] = []
        for notif in notifications:
            eid = _derive_event_id(notif)
            already_processed = conn.execute("SELECT 1 FROM events WHERE event_id = ? AND is_duplicate = 0", (eid,)).fetchone()
            is_dup = 1 if already_processed else 0
            conn.execute(
                "INSERT INTO events (event_id, seen_at, invocation_id, is_duplicate, source, notification_type) VALUES (?, ?, ?, ?, ?, ?)",
                (eid, now, invocation_id, is_dup, notif.source, notif.type),
            )
            if suppress and already_processed:
                suppressed.append(notif)
            else:
                novel.append(notif)
        conn.commit()
        conn.close()
        return novel, suppressed
    except Exception:
        # Fail open: ledger error must never suppress legitimate events
        return list(notifications), []


def query_recent(
    db_path: pl.Path,
    *,
    limit: int = 50,
) -> list[dict[str, object]]:
    """Return the most recent ledger entries, newest first."""
    try:
        conn = _open(db_path)
        rows = conn.execute(
            "SELECT event_id, seen_at, invocation_id, is_duplicate, source, notification_type FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        keys = ("event_id", "seen_at", "invocation_id", "is_duplicate", "source", "notification_type")
        return [dict(zip(keys, row)) for row in rows]
    except Exception:
        return []


def duplicate_stats(db_path: pl.Path) -> dict[str, int]:
    """Return total, novel, and duplicate counts from the ledger."""
    try:
        conn = _open(db_path)
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        dups = conn.execute("SELECT COUNT(*) FROM events WHERE is_duplicate = 1").fetchone()[0]
        conn.close()
        return {"total": total, "novel": total - dups, "duplicates": dups}
    except Exception:
        return {"total": 0, "novel": 0, "duplicates": 0}
