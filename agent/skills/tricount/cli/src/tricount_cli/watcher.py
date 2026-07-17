"""Notification-emitting watcher daemon for tricount.

Polls all joined tricounts on an interval and writes notification JSON files
into the notifications dir whenever an expense is added, edited, deleted,
settled/reimbursed, or a new member joins.

State lives in ``~/.tricount/watch-state.json`` and is saved atomically after
each successful poll. On first run (or the first time a tricount is seen) the
current state is recorded SILENTLY so pre-existing history never notifies:
only post-seed deltas produce notifications.

The on-disk notification format (source, type, arbitrary fields, timestamp,
filename ``<micros>-tricount-<type>.json``, tmp+rename) matches the other
daemon skills (microsoft/tasks/telegram).
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from . import config
from .client import Transaction, Tricount, TricountClient

STATE_FILE = config.CONFIG_DIR / "watch-state.json"

DEFAULT_INTERVAL = 120


# ---------------------------------------------------------------------------
# Notification writing (matches microsoft/tasks/telegram schema)
# ---------------------------------------------------------------------------


def write_notification(notif_dir: Path, type_: str, **fields: object) -> None:
    """Atomically write a ``source=tricount`` notification JSON file.

    Same shape/filename/atomicity as the other daemon skills: a dict with
    ``source``, ``type``, the given fields (None values dropped), and a
    ``timestamp``, written to ``<micros>-tricount-<type>.json`` via tmp+rename.
    """
    notif_dir.mkdir(parents=True, exist_ok=True)
    notif = {
        "source": "tricount",
        "type": type_,
        **{k: v for k, v in fields.items() if v is not None},
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    filename = f"{int(time.time() * 1e6)}-tricount-{type_}.json"
    tmp = notif_dir / f"{filename}.tmp"
    tmp.write_text(json.dumps(notif, indent=2, ensure_ascii=False))
    tmp.replace(notif_dir / filename)


# ---------------------------------------------------------------------------
# State + hashing
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    ts = datetime.now(UTC).replace(microsecond=0).isoformat()
    print(f"{ts} tricount-watch: {msg}", file=sys.stderr, flush=True)


def entry_hash(tx: Transaction) -> str:
    """Content hash of the fields that a notification should react to."""
    allocations = sorted((a.membership_uuid, a.amount.value) for a in tx.allocations)
    payload = json.dumps(
        {
            "amount": tx.amount.value,
            "description": tx.description,
            "payer": tx.payer_uuid,
            "allocations": allocations,
            "deleted": tx.status != "ACTIVE",
            "type": tx.tx_type,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def snapshot_tricount(t: Tricount) -> dict:
    """Build the stored-state snapshot for a tricount.

    entries: id -> {hash, description, amount, payer, type, deleted}
    members: uuid -> display_name
    """
    members = {m.uuid: m.display_name for m in t.members}
    entries: dict[str, dict] = {}
    for tx in t.transactions:
        entries[str(tx.id)] = {
            "hash": entry_hash(tx),
            "description": tx.description,
            "amount": tx.amount.abs_float,
            "payer": tx.payer_uuid,
            "payer_name": members.get(tx.payer_uuid, "Someone"),
            "type": tx.tx_type,
            "deleted": tx.status != "ACTIVE",
        }
    return {"title": t.title, "currency": t.currency, "entries": entries, "members": members}


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            _log(f"could not read state file ({e}); treating as empty (will re-seed)")
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    tmp.replace(STATE_FILE)


# ---------------------------------------------------------------------------
# Diffing / notification building
# ---------------------------------------------------------------------------


def _payer_name(t: Tricount, payer_uuid: str) -> str:
    m = t.member_by_uuid(payer_uuid)
    return m.display_name if m else "Someone"


def _fmt_amount(amount: float, currency: str) -> str:
    return f"{currency} {amount:.2f}"


def _notify_member_joins(notif_dir: Path, t: Tricount, prev_members: dict) -> None:
    for m in t.members:
        if m.uuid not in prev_members and m.status == "ACTIVE":
            write_notification(
                notif_dir,
                "member_joined",
                interrupt=False,
                tricount=t.title,
                member=m.display_name,
                message=f"{m.display_name} joined '{t.title}'",
            )
            _log(f"[{t.title}] member joined: {m.display_name}")


def _notify_hard_deletes(notif_dir: Path, title: str, prev_entries: dict, current_by_id: dict, currency: str) -> None:
    """Entries that vanished entirely from the API (hard delete)."""
    for entry_id, prev_entry in prev_entries.items():
        if entry_id in current_by_id:
            continue
        if prev_entry.get("deleted", False):
            continue  # already notified as deleted
        _emit_delete(notif_dir, title, prev_entry, currency)


def diff_tricount(t: Tricount, prev: dict, notif_dir: Path) -> None:
    """Compare current tricount state against the stored snapshot and emit
    notifications for every delta. ``prev`` is the previously stored snapshot
    for this tricount (its 'entries'/'members' maps)."""
    prev_entries: dict = prev.get("entries", {})
    prev_members: dict = prev.get("members", {})
    currency = t.currency
    title = t.title

    current_by_id = {str(tx.id): tx for tx in t.transactions}

    # New member joined (nice-to-have)
    _notify_member_joins(notif_dir, t, prev_members)

    # Entries: additions, edits, settlements
    for entry_id, tx in current_by_id.items():
        deleted_now = tx.status != "ACTIVE"
        h = entry_hash(tx)
        who = _payer_name(t, tx.payer_uuid)
        amt = _fmt_amount(tx.amount.abs_float, currency)
        desc = tx.description or "(no description)"

        if entry_id not in prev_entries:
            # Newly-seen entry. If it's already deleted, don't notify (nothing to report).
            if deleted_now:
                continue
            if tx.tx_type in ("BALANCE", "INCOME"):
                _emit_settlement(notif_dir, t, tx, "add")
            else:
                write_notification(
                    notif_dir,
                    "add",
                    interrupt=False,
                    tricount=title,
                    entry_id=int(entry_id),
                    who=who,
                    description=tx.description,
                    amount=tx.amount.abs_float,
                    currency=currency,
                    entry_type=tx.tx_type,
                    message=f"{who} added '{desc}' {amt} to '{title}'",
                )
                _log(f"[{title}] add: {who} '{desc}' {amt}")
            continue

        prev_entry = prev_entries[entry_id]
        prev_deleted = prev_entry.get("deleted", False)

        if h == prev_entry.get("hash"):
            continue  # unchanged

        # Hash changed. Was it a transition to deleted?
        if deleted_now and not prev_deleted:
            _emit_delete(notif_dir, title, prev_entry, currency)
            continue
        if deleted_now and prev_deleted:
            continue  # already-deleted, some other field churned; ignore

        # A real edit of a live entry.
        if tx.tx_type in ("BALANCE", "INCOME"):
            _emit_settlement(notif_dir, t, tx, "edit")
        else:
            write_notification(
                notif_dir,
                "edit",
                interrupt=False,
                tricount=title,
                entry_id=int(entry_id),
                who=who,
                description=tx.description,
                amount=tx.amount.abs_float,
                currency=currency,
                entry_type=tx.tx_type,
                message=f"{who} edited '{desc}' in '{title}'",
            )
            _log(f"[{title}] edit: '{desc}' {amt}")

    _notify_hard_deletes(notif_dir, title, prev_entries, current_by_id, currency)


def _emit_delete(notif_dir: Path, title: str, prev_entry: dict, currency: str) -> None:
    who = prev_entry.get("payer_name") or "Someone"
    desc = prev_entry.get("description") or "(no description)"
    amount = prev_entry.get("amount")
    amt = _fmt_amount(amount, currency) if isinstance(amount, (int, float)) else ""
    # The API doesn't attribute deletions, so name the original payer of the expense.
    message = f"{who}'s expense '{desc}' {amt} was deleted from '{title}'".strip()
    write_notification(
        notif_dir,
        "delete",
        interrupt=False,
        tricount=title,
        who=who,
        description=prev_entry.get("description"),
        amount=amount,
        currency=currency,
        message=message,
    )
    _log(f"[{title}] delete: '{desc}' {amt}")


def _emit_settlement(notif_dir: Path, t: Tricount, tx: Transaction, action: str) -> None:
    """Settlement/reimbursement (BALANCE / INCOME) notification."""
    title = t.title
    currency = t.currency
    payer = _payer_name(t, tx.payer_uuid)
    amt = _fmt_amount(tx.amount.abs_float, currency)
    # The recipient is the (non-payer) allocation, if any.
    recipient = None
    for a in tx.allocations:
        if a.membership_uuid != tx.payer_uuid and a.amount.abs_float > 0:
            m = t.member_by_uuid(a.membership_uuid)
            recipient = m.display_name if m else None
            break
    verb = "reimbursed" if tx.tx_type == "INCOME" else "settled up with"
    if recipient:
        message = f"{payer} {verb} {recipient} for {amt} in '{title}'"
    else:
        message = f"{payer} recorded a {tx.tx_type.lower()} of {amt} in '{title}'"
    write_notification(
        notif_dir,
        "settled",
        interrupt=False,
        tricount=title,
        who=payer,
        recipient=recipient,
        amount=tx.amount.abs_float,
        currency=currency,
        entry_type=tx.tx_type,
        action=action,
        message=message,
    )
    _log(f"[{title}] settled ({action}): {message}")


# ---------------------------------------------------------------------------
# Poll loop
# ---------------------------------------------------------------------------


def poll_once(client: TricountClient, notif_dir: Path, state: dict) -> dict:
    """Poll all joined tricounts once. Mutates and returns updated state.

    First-run seed: if a tricount has no stored snapshot, record it silently.
    """
    tricounts = client.list_tricounts()
    for t in tricounts:
        key = str(t.id)
        snap = snapshot_tricount(t)
        if key not in state:
            # First time seeing this tricount: seed silently.
            state[key] = snap
            _log(f"[{t.title}] seeded silently ({len(snap['entries'])} entries, {len(snap['members'])} members)")
            continue
        try:
            diff_tricount(t, state[key], notif_dir)
        finally:
            # Always advance stored state to the freshly observed snapshot so we
            # never double-notify, even if a single notification write failed.
            state[key] = snap
    return state


def serve(notif_dir: Path, interval: int = DEFAULT_INTERVAL) -> None:
    """Long-running watcher loop. Never crashes on transient API/auth errors."""
    notif_dir.mkdir(parents=True, exist_ok=True)
    client = TricountClient()
    state = load_state()
    seeding = not state
    _log(f"starting (interval={interval}s, notif_dir={notif_dir}, {'fresh seed' if seeding else 'resuming'})")

    while True:
        try:
            state = poll_once(client, notif_dir, state)
            save_state(state)
        except Exception as e:
            _log(f"poll failed ({type(e).__name__}: {e}); continuing")
        time.sleep(interval)
