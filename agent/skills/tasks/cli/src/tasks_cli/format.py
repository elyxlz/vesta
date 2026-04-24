"""Compact text formatters for tasks CLI output."""

from typing import Any

_PRIORITY_LABEL = {1: "low", 2: "norm", 3: "high"}


def _trunc(value: Any, width: int) -> str:
    flat = str(value or "-").replace("\t", " ").replace("\n", " ").replace("\r", " ").strip()
    return flat if len(flat) <= width else flat[: width - 3] + "..."


def _pick(d: dict, k: str, default: Any = "") -> Any:
    return d[k] if k in d else default


def _prio(p: Any) -> str:
    return _PRIORITY_LABEL[p] if p in _PRIORITY_LABEL else (str(p) if p is not None else "-")


def format_task_list(tasks: list[dict[str, Any]]) -> str:
    """One line per task: status  prio  due  id  title."""
    if not tasks:
        return "(no tasks)"
    return "\n".join(
        f"{_trunc(_pick(t, 'status', '-'), 8)}\t"
        f"{_prio(_pick(t, 'priority', None))}\t"
        f"{_trunc(_pick(t, 'due_date', None), 20)}\t"
        f"{_pick(t, 'id')}\t"
        f"{_trunc(_pick(t, 'title'), 80)}"
        for t in tasks
    )


def format_reminder_list(reminders: list[dict[str, Any]]) -> str:
    """One line per reminder: next_run  id  schedule  message (task=<id> if linked; * if auto)."""
    if not reminders:
        return "(no reminders)"
    rows = []
    for r in reminders:
        auto = " *" if _pick(r, "auto_generated", False) else ""
        suffix = f"\ttask={r['task_id']}" if _pick(r, "task_id", None) else ""
        rows.append(
            f"{_trunc(_pick(r, 'next_run', None), 25)}\t"
            f"{_pick(r, 'id')}\t"
            f"{_trunc(_pick(r, 'schedule', None), 40)}\t"
            f"{_trunc(_pick(r, 'message'), 80)}{auto}{suffix}"
        )
    return "\n".join(rows)
