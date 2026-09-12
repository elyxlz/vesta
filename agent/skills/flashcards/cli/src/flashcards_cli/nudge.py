"""The daemon's one job: tell the agent when cards are waiting, at a pace the settings allow."""

import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

from .commands import due_summary
from .db import get_meta, iso, parse_datetime, set_meta
from .settings import load_settings, within_active_hours

SOURCE = "flashcards"
LAST_NUDGE_KEY = "last_nudge_at"


def write_notification(notif_dir: Path, type_: str, **fields: str | int | bool) -> Path:
    """Atomically write one `source=flashcards` notification; the single owner of the on-disk shape."""
    notif_dir.mkdir(parents=True, exist_ok=True)
    notif = {"source": SOURCE, "type": type_, **fields, "timestamp": iso(datetime.now().astimezone())}
    target = notif_dir / f"{time.time_ns()}-{SOURCE}-{type_}.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(notif))
    tmp.replace(target)
    return target


def _nudge_message(total: int, decks: dict[str, int]) -> str:
    by_deck = ", ".join(f"{name} {count}" for name, count in decks.items())
    noun = "flashcard is" if total == 1 else "flashcards are"
    return (
        f"{total} {noun} due ({by_deck}). When the user has a free moment, quiz them: "
        "`flashcards next` gives the card, `flashcards review <id> <again|hard|good|easy>` records the answer."
    )


def tick(conn: sqlite3.Connection, notif_dir: Path, *, now: datetime) -> bool:
    """One pass: writes a `cards_due` notification when cards are due, the nudge interval has elapsed
    since the last one, and the local clock is inside the active hours. Returns whether it wrote."""
    settings = load_settings(conn)
    if settings.nudge_interval_minutes == 0 or not within_active_hours(settings, now.astimezone()):
        return False
    last = get_meta(conn, LAST_NUDGE_KEY)
    if last is not None and now - parse_datetime(last) < timedelta(minutes=settings.nudge_interval_minutes):
        return False
    summary = due_summary(conn, settings, now=now)
    if summary["total"] == 0:
        return False
    write_notification(
        notif_dir,
        "cards_due",
        message=_nudge_message(summary["total"], summary["decks"]),
        due_count=summary["total"],
        decks=", ".join(f"{name} {count}" for name, count in summary["decks"].items()),
        interrupt=False,
    )
    set_meta(conn, LAST_NUDGE_KEY, iso(now))
    return True
