"""Compact text formatters for tasks CLI output."""

from typing import Any

_MAX_TITLE = 80
_MAX_MESSAGE = 80
_MAX_SCHEDULE = 40
_PRIORITY_LABEL = {1: "low", 2: "norm", 3: "high"}


def _trunc(value: str, width: int) -> str:
    flat = value.replace("\t", " ").replace("\n", " ").replace("\r", " ").strip()
    if len(flat) <= width:
        return flat
    return flat[: width - 3] + "..."


def _priority_label(value: Any) -> str:
    if isinstance(value, int) and value in _PRIORITY_LABEL:
        return _PRIORITY_LABEL[value]
    return str(value) if value is not None else "-"


def format_task_list(tasks: list[dict[str, Any]]) -> str:
    """One line per task: status  prio  due  id  title."""
    if not tasks:
        return "(no tasks)"
    lines = []
    for t in tasks:
        status = _trunc(t["status"] if "status" in t else "-", 8)
        prio = _priority_label(t["priority"] if "priority" in t else None)
        due = _trunc(t["due_date"] if "due_date" in t and t["due_date"] else "-", 20)
        task_id = t["id"] if "id" in t else ""
        title = _trunc(t["title"] if "title" in t else "", _MAX_TITLE)
        lines.append(f"{status}\t{prio}\t{due}\t{task_id}\t{title}")
    return "\n".join(lines)


def format_reminder_list(reminders: list[dict[str, Any]]) -> str:
    """One line per reminder: next_run  id  schedule  message (task=<id> if linked; * if auto)."""
    if not reminders:
        return "(no reminders)"
    lines = []
    for r in reminders:
        next_run = _trunc(r["next_run"] if "next_run" in r and r["next_run"] else "-", 25)
        rem_id = r["id"] if "id" in r else ""
        schedule = _trunc(r["schedule"] if "schedule" in r and r["schedule"] else "-", _MAX_SCHEDULE)
        message = _trunc(r["message"] if "message" in r else "", _MAX_MESSAGE)
        auto = " *" if ("auto_generated" in r and r["auto_generated"]) else ""
        suffix = ""
        if "task_id" in r and r["task_id"]:
            suffix = f"\ttask={r['task_id']}"
        lines.append(f"{next_run}\t{rem_id}\t{schedule}\t{message}{auto}{suffix}")
    return "\n".join(lines)
