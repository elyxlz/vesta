"""Compact text formatters for reminders CLI output."""

from datetime import UTC, datetime, timedelta
from typing import Any

from .db import parse_datetime


def _trunc(value: Any, width: int) -> str:
    flat = str(value or "-").replace("\t", " ").replace("\n", " ").replace("\r", " ").strip()
    return flat if len(flat) <= width else flat[: width - 3] + "..."


def _pick(d: dict, k: str, default: Any = "") -> Any:
    return d[k] if k in d else default


def rel_delta(delta: timedelta) -> str:
    """A duration as one coarse unit: 45m, 3h, 2d, 3w."""
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 5400:
        return f"{max(seconds // 60, 1)}m"
    if seconds < 129600:
        return f"{round(seconds / 3600)}h"
    if seconds < 1209600:
        return f"{round(seconds / 86400)}d"
    return f"{round(seconds / 604800)}w"


def rel_time(iso: str | None, now: datetime) -> str:
    """An instant relative to now: 'in 3h', '2d ago', '-' when unset."""
    if not iso:
        return "-"
    instant = parse_datetime(iso)
    if instant >= now:
        return f"in {rel_delta(instant - now)}"
    return f"{rel_delta(now - instant)} ago"


def format_reminder_list(reminders: list[dict[str, Any]], now: datetime | None = None) -> str:
    """One line per reminder: next_run  id  schedule  message."""
    if not reminders:
        return "(no reminders)"
    now = now or datetime.now(UTC)
    rows = []
    for r in reminders:
        fired = "[fired] " if _pick(r, "status", None) == "completed" else ""
        rows.append(
            f"{rel_time(_pick(r, 'next_run', None), now)}\t"
            f"{_pick(r, 'id')}\t"
            f"{_trunc(_pick(r, 'schedule', None), 40)}\t"
            f"{fired}{_trunc(_pick(r, 'message'), 80)}"
        )
    return "\n".join(rows)
