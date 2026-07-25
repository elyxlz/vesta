#!/usr/bin/env python3
"""Undo-send queue for held outbound mail (``--hold`` on email-client-send).

A held send is one JSON file at ``$EMAIL_CLIENT_DIR/pending-sends/<token>.json``
storing the fully composed message (recipients, threading headers, attachments)
plus a fire-at timestamp. The poll daemon dispatches entries whose fire-at has
passed. Cancel unlinks the entry; dispatch claims one by renaming it to
``<token>.sending`` first, so cancel and dispatch can never both win. A failed
dispatch is renamed to ``<token>.failed`` (with the error inside) and is never
retried: retrying a maybe-sent message risks a double send. A ``.sending`` file
left by a crash mid-dispatch is kept for the same reason.

Dependency-free (no imap_tools/msal) so it unit-tests without the on-box
runtime, mirroring daemon_lifecycle.py.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import uuid

QUEUE_DIR_NAME = "pending-sends"


@dataclasses.dataclass(frozen=True)
class HeldAttachment:
    """One attachment of a held send, content stored base64-encoded."""

    name: str
    maintype: str
    subtype: str
    data_b64: str


@dataclasses.dataclass(frozen=True)
class HeldSend:
    """A fully composed outbound message waiting out its undo window."""

    token: str
    fire_at: float
    created_at: float
    account: str
    user: str
    display: str
    to: str
    subject: str
    body: str
    body_html: str | None
    cc: list[str]
    bcc: list[str]
    in_reply_to: str
    references: str
    attachments: list[HeldAttachment]
    sent_sync: bool
    reply_to_uid: str | None
    reply_folder: str


def new_token() -> str:
    return uuid.uuid4().hex[:12]


def queue_dir(state_dir: pathlib.Path) -> pathlib.Path:
    d = state_dir / QUEUE_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def entry_path(qdir: pathlib.Path, token: str) -> pathlib.Path:
    return qdir / f"{token}.json"


def save(qdir: pathlib.Path, entry: HeldSend) -> pathlib.Path:
    """Atomically write the entry (tmp + rename) so a reader never sees a torn file."""
    final = entry_path(qdir, entry.token)
    tmp = final.with_suffix(".tmp")
    tmp.write_text(json.dumps(dataclasses.asdict(entry), ensure_ascii=False))
    tmp.replace(final)
    return final


def load(path: pathlib.Path) -> HeldSend:
    data = json.loads(path.read_text())
    data["attachments"] = [HeldAttachment(**a) for a in data["attachments"]]
    return HeldSend(**data)


def cancel(qdir: pathlib.Path, token: str) -> bool:
    """Remove a pending entry. False when it already fired (or never existed)."""
    try:
        entry_path(qdir, token).unlink()
    except FileNotFoundError:
        return False
    return True


def list_pending(qdir: pathlib.Path) -> list[HeldSend]:
    return sorted((load(p) for p in qdir.glob("*.json")), key=lambda e: e.fire_at)


def claim_due(qdir: pathlib.Path, now: float) -> list[tuple[pathlib.Path, HeldSend]]:
    """Claim every entry whose fire-at has passed by renaming it to ``<token>.sending``.

    The rename is atomic, so a concurrent cancel either removed the entry first
    (the rename raises and the entry is skipped) or lost and is told so.
    """
    claimed: list[tuple[pathlib.Path, HeldSend]] = []
    for path in sorted(qdir.glob("*.json")):
        entry = load(path)
        if entry.fire_at > now:
            continue
        sending = path.with_suffix(".sending")
        try:
            path.rename(sending)
        except FileNotFoundError:
            continue
        claimed.append((sending, entry))
    return claimed


def fail(claimed_path: pathlib.Path, error: str) -> pathlib.Path:
    """Park a claimed entry as ``<token>.failed`` with the error recorded inside."""
    data = json.loads(claimed_path.read_text())
    data["error"] = error
    failed = claimed_path.with_suffix(".failed")
    failed.write_text(json.dumps(data, ensure_ascii=False))
    claimed_path.unlink(missing_ok=True)
    return failed
