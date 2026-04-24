"""Compact text formatters and metadata strippers for Microsoft CLI output."""

from typing import Any

_MAX_SUBJECT = 80
_MAX_ADDR = 48
_MAX_LOC = 32
_DATE_WIDTH = 20


def strip_odata(obj: Any) -> Any:
    """Recursively drop keys starting with `@odata.` from dicts and lists."""
    if isinstance(obj, dict):
        return {k: strip_odata(v) for k, v in obj.items() if not k.startswith("@odata.")}
    if isinstance(obj, list):
        return [strip_odata(item) for item in obj]
    return obj


def _trunc(value: str, width: int) -> str:
    flat = value.replace("\t", " ").replace("\n", " ").replace("\r", " ").strip()
    if len(flat) <= width:
        return flat
    return flat[: width - 3] + "..."


def _from_addr(record: dict[str, Any]) -> str:
    if "from" not in record:
        return ""
    f = record["from"]
    if not isinstance(f, dict) or "emailAddress" not in f:
        return ""
    ea = f["emailAddress"]
    if not isinstance(ea, dict) or "address" not in ea:
        return ""
    addr = ea["address"]
    return addr.strip() if isinstance(addr, str) else ""


def _event_time(record: dict[str, Any], key: str) -> str:
    if key not in record:
        return ""
    v = record[key]
    if not isinstance(v, dict) or "dateTime" not in v:
        return ""
    dt = v["dateTime"]
    return dt.strip() if isinstance(dt, str) else ""


def format_email_list(emails: list[dict[str, Any]]) -> str:
    """One line per message: date  from  subject  [*unread]  id."""
    if not emails:
        return "(no messages)"
    lines = []
    for e in emails:
        date = _trunc(e["receivedDateTime"] if "receivedDateTime" in e else "", _DATE_WIDTH)
        from_addr = _trunc(_from_addr(e), _MAX_ADDR)
        subject = _trunc(e["subject"] if "subject" in e else "", _MAX_SUBJECT)
        unread = " *" if ("isRead" in e and not e["isRead"]) else ""
        msg_id = e["id"] if "id" in e else ""
        lines.append(f"{date}\t{from_addr}\t{subject}{unread}\t{msg_id}")
    return "\n".join(lines)


def format_calendar_event_list(events: list[dict[str, Any]]) -> str:
    """One line per event: start  end  subject  location  id."""
    if not events:
        return "(no events)"
    lines = []
    for e in events:
        start = _trunc(_event_time(e, "start"), _DATE_WIDTH)
        end = _trunc(_event_time(e, "end"), _DATE_WIDTH)
        subject = _trunc(e["subject"] if "subject" in e else "", _MAX_SUBJECT)
        loc = ""
        if "location" in e and isinstance(e["location"], dict) and "displayName" in e["location"]:
            raw_loc = e["location"]["displayName"]
            loc = _trunc(raw_loc if isinstance(raw_loc, str) else "", _MAX_LOC)
        event_id = e["id"] if "id" in e else ""
        lines.append(f"{start}\t{end}\t{subject}\t{loc}\t{event_id}")
    return "\n".join(lines)


def format_calendar_name_list(calendars: list[dict[str, Any]]) -> str:
    """One line per calendar: default-marker  name  id."""
    if not calendars:
        return "(no calendars)"
    lines = []
    for c in calendars:
        default = "*" if ("isDefaultCalendar" in c and c["isDefaultCalendar"]) else " "
        name = _trunc(c["name"] if "name" in c else "", 40)
        cal_id = c["id"] if "id" in c else ""
        lines.append(f"{default}\t{name}\t{cal_id}")
    return "\n".join(lines)
