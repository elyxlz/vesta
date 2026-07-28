"""Durable delayed-send state owned by the email client."""

from __future__ import annotations

import contextlib
import sqlite3
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_DELAY_SECONDS = 30
RETRY_DELAY_SECONDS = 30
_DATABASE_NAME = "pending-sends.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sends (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    send_at TEXT NOT NULL,
    account TEXT NOT NULL,
    action TEXT NOT NULL,
    subject TEXT NOT NULL,
    recipients TEXT NOT NULL,
    backend TEXT NOT NULL,
    payload BLOB NOT NULL,
    state TEXT NOT NULL,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS sends_due ON sends(state, send_at);
"""


@dataclass(frozen=True)
class PendingSend:
    id: str
    created_at: datetime
    send_at: datetime
    account: str
    action: str
    subject: str
    recipients: str
    backend: str
    payload: bytes

    def public(self) -> dict[str, str]:
        return {
            "id": self.id,
            "status": "pending",
            "account": self.account,
            "action": self.action,
            "subject": self.subject,
            "recipients": self.recipients,
            "send_at": self.send_at.isoformat(),
        }


@contextlib.contextmanager
def _connection(data_dir: Path) -> Iterator[sqlite3.Connection]:
    data_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(data_dir / _DATABASE_NAME)
    try:
        connection.executescript(_SCHEMA)
        yield connection
        connection.commit()
    finally:
        connection.close()


def _from_row(row: sqlite3.Row | tuple) -> PendingSend:
    return PendingSend(
        id=str(row[0]),
        created_at=datetime.fromisoformat(str(row[1])),
        send_at=datetime.fromisoformat(str(row[2])),
        account=str(row[3]),
        action=str(row[4]),
        subject=str(row[5]),
        recipients=str(row[6]),
        backend=str(row[7]),
        payload=bytes(row[8]),
    )


def delay_seconds(data_dir: Path) -> int:
    with _connection(data_dir) as connection:
        row = connection.execute("SELECT value FROM settings WHERE key = 'send_delay_seconds'").fetchone()
    return int(row[0]) if row is not None else DEFAULT_DELAY_SECONDS


def set_delay_seconds(data_dir: Path, seconds: int) -> int:
    if seconds < 0:
        raise ValueError("send delay must be zero or greater")
    with _connection(data_dir) as connection:
        connection.execute(
            "INSERT INTO settings(key, value) VALUES('send_delay_seconds', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (seconds,),
        )
    return seconds


def enqueue(
    data_dir: Path,
    *,
    account: str,
    action: str,
    subject: str,
    recipients: str,
    backend: str,
    payload: bytes,
    now: datetime | None = None,
) -> PendingSend:
    created_at = now or datetime.now(UTC)
    queued = PendingSend(
        id=uuid.uuid4().hex,
        created_at=created_at,
        send_at=created_at + timedelta(seconds=delay_seconds(data_dir)),
        account=account,
        action=action,
        subject=subject,
        recipients=recipients,
        backend=backend,
        payload=payload,
    )
    with _connection(data_dir) as connection:
        connection.execute(
            "INSERT INTO sends(id, created_at, send_at, account, action, subject, recipients, backend, payload, state) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (
                queued.id,
                queued.created_at.isoformat(),
                queued.send_at.isoformat(),
                queued.account,
                queued.action,
                queued.subject,
                queued.recipients,
                queued.backend,
                queued.payload,
            ),
        )
    return queued


def list_pending(data_dir: Path, *, account: str | None = None, now: datetime | None = None) -> list[PendingSend]:
    undoable_at = now or datetime.now(UTC)
    with _connection(data_dir) as connection:
        if account is None:
            rows = connection.execute(
                "SELECT id, created_at, send_at, account, action, subject, recipients, backend, payload "
                "FROM sends WHERE state = 'pending' AND send_at > ? ORDER BY send_at, id",
                (undoable_at.isoformat(),),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT id, created_at, send_at, account, action, subject, recipients, backend, payload "
                "FROM sends WHERE state = 'pending' AND account = ? AND send_at > ? ORDER BY send_at, id",
                (account, undoable_at.isoformat()),
            ).fetchall()
    return [_from_row(row) for row in rows]


def cancel(data_dir: Path, pending_id: str, *, now: datetime | None = None) -> PendingSend:
    cancel_at = now or datetime.now(UTC)
    with _connection(data_dir) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT id, created_at, send_at, account, action, subject, recipients, backend, payload "
            "FROM sends WHERE id = ? AND state = 'pending' AND send_at > ?",
            (pending_id, cancel_at.isoformat()),
        ).fetchone()
        if row is None:
            raise ValueError(f"pending send {pending_id!r} was not found, has expired, or has already been delivered")
        connection.execute("UPDATE sends SET state = 'cancelled' WHERE id = ?", (pending_id,))
    return _from_row(row)


def finish_cancel(data_dir: Path, pending_id: str) -> None:
    with _connection(data_dir) as connection:
        connection.execute("DELETE FROM sends WHERE id = ? AND state = 'cancelled'", (pending_id,))


def claim_due(data_dir: Path, *, now: datetime | None = None) -> PendingSend | None:
    due_at = now or datetime.now(UTC)
    with _connection(data_dir) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT id, created_at, send_at, account, action, subject, recipients, backend, payload "
            "FROM sends WHERE state = 'pending' AND send_at <= ? ORDER BY send_at, id LIMIT 1",
            (due_at.isoformat(),),
        ).fetchone()
        if row is None:
            return None
        connection.execute("UPDATE sends SET state = 'dispatching' WHERE id = ?", (str(row[0]),))
    return _from_row(row)


def complete(data_dir: Path, pending_id: str) -> None:
    with _connection(data_dir) as connection:
        connection.execute("DELETE FROM sends WHERE id = ? AND state = 'dispatching'", (pending_id,))


def retry(data_dir: Path, pending_id: str, error: str, *, now: datetime | None = None) -> None:
    retry_at = (now or datetime.now(UTC)) + timedelta(seconds=RETRY_DELAY_SECONDS)
    with _connection(data_dir) as connection:
        connection.execute(
            "UPDATE sends SET state = 'pending', send_at = ?, last_error = ? WHERE id = ? AND state = 'dispatching'",
            (retry_at.isoformat(), error, pending_id),
        )


def recover_dispatching(data_dir: Path) -> None:
    with _connection(data_dir) as connection:
        connection.execute("UPDATE sends SET state = 'pending' WHERE state = 'dispatching'")
