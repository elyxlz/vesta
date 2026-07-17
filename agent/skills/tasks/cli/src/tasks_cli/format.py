"""Compact text formatters for tasks CLI output."""

from datetime import UTC, datetime, timedelta
from typing import Any

from .db import parse_datetime

PRIORITY_LABEL = {1: "low", 2: "norm", 3: "high"}


def _trunc(value: Any, width: int) -> str:
    flat = str(value or "-").replace("\t", " ").replace("\n", " ").replace("\r", " ").strip()
    return flat if len(flat) <= width else flat[: width - 3] + "..."


def _pick(d: dict, k: str, default: Any = "") -> Any:
    return d[k] if k in d else default


def _prio(p: Any) -> str:
    return PRIORITY_LABEL[p] if p in PRIORITY_LABEL else (str(p) if p is not None else "-")


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


def _due_col(iso: str | None, now: datetime) -> str:
    if not iso:
        return "-"
    due = parse_datetime(iso)
    if due >= now:
        return f"due in {rel_delta(due - now)}"
    return f"OVERDUE {rel_delta(now - due)}"


def format_task_list(tasks: list[dict[str, Any]], now: datetime | None = None) -> str:
    """One line per task: status  prio  due  id  title."""
    if not tasks:
        return "(no tasks)"
    now = now or datetime.now(UTC)
    return "\n".join(
        f"{_trunc(_pick(t, 'status', '-'), 8)}\t"
        f"{_prio(_pick(t, 'priority', None))}\t"
        f"{_due_col(_pick(t, 'due_date', None), now)}\t"
        f"{_pick(t, 'id')}\t"
        f"{_trunc(_pick(t, 'title'), 80)}"
        for t in tasks
    )


def format_reminder_list(reminders: list[dict[str, Any]], now: datetime | None = None) -> str:
    """One line per reminder: next_run  id  schedule  message (task=<id> if linked; * if auto)."""
    if not reminders:
        return "(no reminders)"
    now = now or datetime.now(UTC)
    rows = []
    for r in reminders:
        auto = " *" if _pick(r, "auto_generated", False) else ""
        suffix = f"\ttask={r['task_id']}" if _pick(r, "task_id", None) else ""
        rows.append(
            f"{rel_time(_pick(r, 'next_run', None), now)}\t"
            f"{_pick(r, 'id')}\t"
            f"{_trunc(_pick(r, 'schedule', None), 40)}\t"
            f"{_trunc(_pick(r, 'message'), 80)}{auto}{suffix}"
        )
    return "\n".join(rows)
