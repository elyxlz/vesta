"""Undo-send queue for held outbound mail (``--hold`` on email send/reply/forward).

A held send is one JSON file at ``<data_dir>/pending-sends/<token>.json`` storing
the fully resolved payload (command, account, backend, MailDraft fields) plus a
fire-at timestamp. The serve daemon's monitor cycle dispatches entries whose
fire-at has passed. Cancel unlinks the entry; dispatch claims one by renaming it
to ``<token>.sending`` first, so cancel and dispatch can never both win. A
failed dispatch is renamed to ``<token>.failed`` (error recorded inside) and is
never retried: retrying a maybe-sent message risks a double send.
"""

import dataclasses
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from . import backend, email, owa_rest_commands
from .config import Config
from .payloads import MailDraft

QUEUE_DIR_NAME = "pending-sends"


@dataclasses.dataclass(frozen=True)
class PendingSend:
    """A held email send/reply/forward waiting out its undo window."""

    token: str
    fire_at: float
    created_at: float
    account: str
    backend: str
    command: str
    mail: MailDraft
    email_id: str | None = None
    reply_all: bool = False


def new_token() -> str:
    return uuid.uuid4().hex[:12]


def queue_dir(config: Config) -> Path:
    d = config.data_dir / QUEUE_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def entry_path(config: Config, token: str) -> Path:
    return queue_dir(config) / f"{token}.json"


def save(config: Config, entry: PendingSend) -> Path:
    """Atomically write the entry (tmp + rename) so a reader never sees a torn file."""
    final = entry_path(config, entry.token)
    tmp = final.with_suffix(".tmp")
    tmp.write_text(json.dumps(dataclasses.asdict(entry)))
    tmp.replace(final)
    return final


def load(path: Path) -> PendingSend:
    data = json.loads(path.read_text())
    data["mail"] = MailDraft(**data["mail"])
    return PendingSend(**data)


def cancel(config: Config, token: str) -> bool:
    """Remove a pending entry. False when it already fired (or never existed)."""
    try:
        entry_path(config, token).unlink()
    except FileNotFoundError:
        return False
    return True


def list_pending(config: Config) -> list[PendingSend]:
    return sorted((load(p) for p in queue_dir(config).glob("*.json")), key=lambda e: e.fire_at)


def describe(entry: PendingSend, now: float) -> dict:
    """One list-pending row: what is held and when it fires."""
    return {
        "token": entry.token,
        "command": entry.command,
        "account": entry.account,
        "to": entry.mail.to,
        "subject": entry.mail.subject,
        "email_id": entry.email_id,
        "fire_at": datetime.fromtimestamp(entry.fire_at, tz=UTC).isoformat(timespec="seconds"),
        "fires_in_seconds": max(0, int(entry.fire_at - now)),
    }


def claim_due(config: Config, now: float) -> list[tuple[Path, PendingSend]]:
    """Claim every entry whose fire-at has passed by renaming it to ``<token>.sending``.

    The rename is atomic, so a concurrent cancel either removed the entry first
    (the rename raises and the entry is skipped) or lost and is told so.
    """
    claimed: list[tuple[Path, PendingSend]] = []
    for path in sorted(queue_dir(config).glob("*.json")):
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


def fail(claimed_path: Path, error: str) -> Path:
    """Park a claimed entry as ``<token>.failed`` with the error recorded inside."""
    data = json.loads(claimed_path.read_text())
    data["error"] = error
    failed = claimed_path.with_suffix(".failed")
    failed.write_text(json.dumps(data))
    claimed_path.unlink(missing_ok=True)
    return failed


def _send_fns(config: Config, client, entry: PendingSend):
    """The (graph, owa-rest) implementations of the held command, mirroring cli's routes."""
    if entry.command == "send":
        kw = {"account_email": entry.account, "mail": entry.mail}
        return (lambda: email.send_email(config, client, **kw), lambda: owa_rest_commands.send_email(config, client, **kw))
    if entry.command == "reply":
        kw = {
            "account_email": entry.account,
            "email_id": entry.email_id,
            "body": entry.mail.body,
            "attachments": entry.mail.attachments,
            "reply_all": entry.reply_all,
            "html": entry.mail.html,
        }
        return (lambda: email.reply_to_email(config, client, **kw), lambda: owa_rest_commands.reply_to_email(config, client, **kw))
    if entry.command == "forward":
        kw = {"account_email": entry.account, "email_id": entry.email_id, "mail": entry.mail}
        return (lambda: email.forward_email(config, client, **kw), lambda: owa_rest_commands.forward_email(config, client, **kw))
    raise ValueError(f"unknown held command {entry.command!r}")


def dispatch_due(config: Config, client, now: float) -> list[tuple[PendingSend, str | None]]:
    """Send every claimed due entry. Returns (entry, error) per attempt, error None on success."""
    outcomes: list[tuple[PendingSend, str | None]] = []
    for claimed, entry in claim_due(config, now):
        graph_fn, rest_fn = _send_fns(config, client, entry)
        try:
            backend.run(entry.backend, graph_fn, rest_fn)
            claimed.unlink(missing_ok=True)
            outcomes.append((entry, None))
        except Exception as e:
            fail(claimed, str(e))
            outcomes.append((entry, str(e)))
    return outcomes
