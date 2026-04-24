"""Compact text formatters and metadata strippers for Microsoft CLI output."""

from typing import Any


def strip_odata(obj: Any) -> Any:
    """Recursively drop keys starting with `@odata.` from dicts and lists."""
    if isinstance(obj, dict):
        return {k: strip_odata(v) for k, v in obj.items() if not k.startswith("@odata.")}
    if isinstance(obj, list):
        return [strip_odata(item) for item in obj]
    return obj


def _trunc(value: Any, width: int) -> str:
    flat = str(value or "").replace("\t", " ").replace("\n", " ").replace("\r", " ").strip()
    return flat if len(flat) <= width else flat[: width - 3] + "..."


def _pick(record: dict, *keys: str) -> Any:
    """Walk nested dict keys; return '' if any segment is missing."""
    cur: Any = record
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return ""
        cur = cur[k]
    return cur


def format_email_list(emails: list[dict[str, Any]]) -> str:
    """One line per message: date  from  subject  [*unread]  id."""
    if not emails:
        return "(no messages)"
    rows = []
    for e in emails:
        unread = " *" if ("isRead" in e and not e["isRead"]) else ""
        rows.append(
            f"{_trunc(_pick(e, 'receivedDateTime'), 20)}\t"
            f"{_trunc(_pick(e, 'from', 'emailAddress', 'address'), 48)}\t"
            f"{_trunc(_pick(e, 'subject'), 80)}{unread}\t"
            f"{_pick(e, 'id')}"
        )
    return "\n".join(rows)


def format_calendar_event_list(events: list[dict[str, Any]]) -> str:
    """One line per event: start  end  subject  location  id."""
    if not events:
        return "(no events)"
    return "\n".join(
        f"{_trunc(_pick(e, 'start', 'dateTime'), 20)}\t"
        f"{_trunc(_pick(e, 'end', 'dateTime'), 20)}\t"
        f"{_trunc(_pick(e, 'subject'), 80)}\t"
        f"{_trunc(_pick(e, 'location', 'displayName'), 32)}\t"
        f"{_pick(e, 'id')}"
        for e in events
    )


def format_calendar_name_list(calendars: list[dict[str, Any]]) -> str:
    """One line per calendar: default-marker  name  id."""
    if not calendars:
        return "(no calendars)"
    return "\n".join(
        f"{'*' if ('isDefaultCalendar' in c and c['isDefaultCalendar']) else ' '}\t{_trunc(_pick(c, 'name'), 40)}\t{_pick(c, 'id')}"
        for c in calendars
    )
