#!/usr/bin/env python3
"""Minimal iCalendar engine for the email-client calendar commands.

Parse, edit, and re-serialize VCALENDAR streams and expand recurring events
into concrete occurrences, stdlib only, so the skill's runtime venv needs no
extra packages. Parsing keeps each property's raw value and parameters, so an
event fetched from a server round-trips through an edit without losing
properties this module does not model.

Recurrence support covers what Google, iCloud, and Fastmail emit in practice:
FREQ daily/weekly/monthly/yearly, INTERVAL, COUNT, UNTIL, WKST, BYDAY (weekly
day lists and monthly ordinals like 2TU or -1FR), BYMONTHDAY, EXDATE, RDATE,
and RECURRENCE-ID overrides. A rule using anything beyond that yields the
master occurrence alone rather than guessing.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Instant = dt.datetime | dt.date

MAX_OCCURRENCES = 1000
MAX_PERIODS = 5000
FOLD_WIDTH = 74

WEEKDAY_CODES = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
SUPPORTED_RRULE_KEYS = {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY", "WKST"}

_MONTHLY_BYDAY_RE = re.compile(r"^([+-]?\d)?(MO|TU|WE|TH|FR|SA|SU)$")
_DT_RE = re.compile(r"^(\d{8})(?:T(\d{6})(Z?))?$")
_DURATION_RE = re.compile(r"^([+-]?)P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


@dataclasses.dataclass
class Prop:
    """One content line: params and value kept raw (still iCal-escaped) for lossless round-trips."""

    name: str
    params: dict[str, str]
    value: str


@dataclasses.dataclass
class Component:
    name: str
    props: list[Prop]
    children: list[Component]


@dataclasses.dataclass
class Occurrence:
    vevent: Component
    start: Instant
    end: Instant


# -- parse ----------------------------------------------------------------


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw:
            continue
        if raw[0] in " \t" and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _split_name_value(line: str) -> tuple[str, str]:
    """Split a content line at the first ':' outside double quotes."""
    in_quotes = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ":" and not in_quotes:
            return line[:i], line[i + 1 :]
    raise ValueError(f"malformed iCalendar line (no ':'): {line[:80]!r}")


def _split_params(head: str) -> tuple[str, dict[str, str]]:
    parts: list[str] = []
    current = ""
    in_quotes = False
    for ch in head:
        if ch == '"':
            in_quotes = not in_quotes
            current += ch
        elif ch == ";" and not in_quotes:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, _, value = part.partition("=")
            params[key.upper()] = value
    return parts[0].upper(), params


def parse(text: str) -> list[Component]:
    roots: list[Component] = []
    stack: list[Component] = []
    for line in _unfold(text):
        head, value = _split_name_value(line)
        name, params = _split_params(head)
        if name == "BEGIN":
            comp = Component(name=value.strip().upper(), props=[], children=[])
            if stack:
                stack[-1].children.append(comp)
            else:
                roots.append(comp)
            stack.append(comp)
        elif name == "END":
            if stack:
                stack.pop()
        elif stack:
            stack[-1].props.append(Prop(name=name, params=params, value=value))
    return roots


def parse_calendar(text: str) -> Component:
    for comp in parse(text):
        if comp.name == "VCALENDAR":
            return comp
    raise ValueError("no VCALENDAR component found")


# -- serialize ------------------------------------------------------------


def _param_text(value: str) -> str:
    if value.startswith('"') or not re.search(r"[;:,]", value):
        return value
    return f'"{value}"'


def _fold(line: str) -> str:
    if len(line) <= FOLD_WIDTH:
        return line
    chunks = [line[:FOLD_WIDTH]]
    rest = line[FOLD_WIDTH:]
    while rest:
        chunks.append(" " + rest[: FOLD_WIDTH - 1])
        rest = rest[FOLD_WIDTH - 1 :]
    return "\r\n".join(chunks)


def _prop_line(prop: Prop) -> str:
    head = prop.name
    for key, value in prop.params.items():
        head += f";{key}={_param_text(value)}"
    return _fold(f"{head}:{prop.value}")


def serialize(comp: Component) -> str:
    lines = [f"BEGIN:{comp.name}"]
    lines.extend(_prop_line(prop) for prop in comp.props)
    lines.extend(serialize(child).rstrip("\r\n") for child in comp.children)
    lines.append(f"END:{comp.name}")
    return "\r\n".join(lines) + "\r\n"


# -- text escaping ----------------------------------------------------------


def escape_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def unescape_text(value: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


# -- component helpers ------------------------------------------------------


def first_prop(comp: Component, name: str) -> Prop | None:
    for prop in comp.props:
        if prop.name == name:
            return prop
    return None


def all_props(comp: Component, name: str) -> list[Prop]:
    return [prop for prop in comp.props if prop.name == name]


def set_prop(comp: Component, name: str, value: str, params: dict[str, str] | None = None) -> None:
    """Replace every property of ``name`` with a single one, keeping its position."""
    new = Prop(name=name, params=dict(params) if params else {}, value=value)
    for i, prop in enumerate(comp.props):
        if prop.name == name:
            comp.props = [p for p in comp.props if p.name != name]
            comp.props.insert(i, new)
            return
    comp.props.append(new)


def remove_props(comp: Component, name: str) -> None:
    comp.props = [prop for prop in comp.props if prop.name != name]


def vevents(vcal: Component) -> list[Component]:
    return [child for child in vcal.children if child.name == "VEVENT"]


# -- date/time --------------------------------------------------------------


def _zone(tzid: str) -> dt.tzinfo:
    try:
        return ZoneInfo(tzid.strip('"'))
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return dt.UTC


def parse_instant(value: str, params: dict[str, str]) -> Instant:
    match = _DT_RE.match(value.strip())
    if not match:
        raise ValueError(f"unparseable iCalendar date/time: {value!r}")
    date_part, time_part, zulu = match.group(1), match.group(2), match.group(3)
    day = dt.date(int(date_part[:4]), int(date_part[4:6]), int(date_part[6:8]))
    if time_part is None or ("VALUE" in params and params["VALUE"].upper() == "DATE"):
        return day
    time_of_day = dt.time(int(time_part[:2]), int(time_part[2:4]), int(time_part[4:6]))
    if zulu:
        return dt.datetime.combine(day, time_of_day, tzinfo=dt.UTC)
    tz = _zone(params["TZID"]) if "TZID" in params else dt.UTC
    return dt.datetime.combine(day, time_of_day, tzinfo=tz)


def prop_instant(prop: Prop) -> Instant:
    return parse_instant(prop.value, prop.params)


def format_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def format_date(value: dt.date) -> str:
    return value.strftime("%Y%m%d")


def as_utc(value: Instant) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.UTC)
    return dt.datetime.combine(value, dt.time(), tzinfo=dt.UTC)


def _parse_duration(value: str) -> dt.timedelta:
    match = _DURATION_RE.match(value.strip())
    if not match:
        return dt.timedelta()
    sign = -1 if match.group(1) == "-" else 1
    weeks, days, hours, minutes, seconds = (int(group) if group else 0 for group in match.groups()[1:])
    return sign * dt.timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds)


def _event_duration(vevent: Component) -> dt.timedelta:
    start_prop = first_prop(vevent, "DTSTART")
    if start_prop is None:
        return dt.timedelta()
    start = prop_instant(start_prop)
    end_prop = first_prop(vevent, "DTEND")
    if end_prop is not None:
        return as_utc(prop_instant(end_prop)) - as_utc(start)
    duration_prop = first_prop(vevent, "DURATION")
    if duration_prop is not None:
        return _parse_duration(duration_prop.value)
    return dt.timedelta() if isinstance(start, dt.datetime) else dt.timedelta(days=1)


# -- recurrence expansion -----------------------------------------------------


def _parse_rrule(rule_text: str) -> dict[str, str]:
    rule: dict[str, str] = {}
    for part in rule_text.split(";"):
        if "=" in part:
            key, _, value = part.partition("=")
            rule[key.strip().upper()] = value.strip()
    return rule


def _shift_month(year: int, month: int, months: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def _days_in_month(year: int, month: int) -> int:
    next_year, next_month = _shift_month(year, month, 1)
    return (dt.date(next_year, next_month, 1) - dt.date(year, month, 1)).days


def _nth_weekday(year: int, month: int, weekday: int, ordinal: int) -> int | None:
    """Day-of-month of the nth (1-based, negative = from the end) given weekday, or None."""
    days = [d for d in range(1, _days_in_month(year, month) + 1) if dt.date(year, month, d).weekday() == weekday]
    if ordinal > 0 and ordinal <= len(days):
        return days[ordinal - 1]
    if ordinal < 0 and -ordinal <= len(days):
        return days[ordinal]
    return None


def _rrule_supported(rule: dict[str, str]) -> bool:
    if "FREQ" not in rule or not SUPPORTED_RRULE_KEYS.issuperset(rule):
        return False
    freq = rule["FREQ"].upper()
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return False
    has_byday = "BYDAY" in rule and rule["BYDAY"]
    has_bymonthday = "BYMONTHDAY" in rule and rule["BYMONTHDAY"]
    if has_byday and freq not in ("WEEKLY", "MONTHLY"):
        return False
    if has_bymonthday and freq != "MONTHLY":
        return False
    if has_byday and has_bymonthday:
        return False
    if has_byday and freq == "WEEKLY":
        if not all(code in WEEKDAY_CODES for code in rule["BYDAY"].split(",")):
            return False
    if has_byday and freq == "MONTHLY":
        if not all(_MONTHLY_BYDAY_RE.match(spec) for spec in rule["BYDAY"].split(",")):
            return False
    return True


def _candidate_starts(rule: dict[str, str], base: dt.datetime) -> list[list[dt.datetime]]:
    """Naive wall-clock candidates >= base, one ascending list per period, bounded by MAX_PERIODS."""
    freq = rule["FREQ"].upper()
    interval = int(rule["INTERVAL"]) if "INTERVAL" in rule else 1
    byday = rule["BYDAY"].split(",") if "BYDAY" in rule and rule["BYDAY"] else []
    periods: list[list[dt.datetime]] = []

    if freq == "DAILY":
        for k in range(MAX_PERIODS):
            periods.append([base + dt.timedelta(days=k * interval)])
    elif freq == "WEEKLY" and not byday:
        for k in range(MAX_PERIODS):
            periods.append([base + dt.timedelta(weeks=k * interval)])
    elif freq == "WEEKLY":
        wkst = WEEKDAY_CODES[rule["WKST"]] if "WKST" in rule and rule["WKST"] in WEEKDAY_CODES else 0
        week_start = base - dt.timedelta(days=(base.weekday() - wkst) % 7)
        offsets = sorted((WEEKDAY_CODES[code] - wkst) % 7 for code in byday)
        for k in range(MAX_PERIODS):
            week = [week_start + dt.timedelta(weeks=k * interval, days=offset) for offset in offsets]
            periods.append([candidate for candidate in week if candidate >= base])
    elif freq == "MONTHLY":
        monthdays = [int(x) for x in rule["BYMONTHDAY"].split(",")] if "BYMONTHDAY" in rule and rule["BYMONTHDAY"] else []
        for k in range(MAX_PERIODS):
            year, month = _shift_month(base.year, base.month, k * interval)
            days: list[int] = []
            if byday:
                for spec in byday:
                    match = _MONTHLY_BYDAY_RE.match(spec)
                    if match is None:
                        continue
                    ordinal = int(match.group(1)) if match.group(1) else 1
                    day = _nth_weekday(year, month, WEEKDAY_CODES[match.group(2)], ordinal)
                    if day is not None:
                        days.append(day)
            else:
                limit = _days_in_month(year, month)
                for monthday in monthdays or [base.day]:
                    resolved = monthday if monthday > 0 else limit + 1 + monthday
                    if 1 <= resolved <= limit:
                        days.append(resolved)
            month_starts = [dt.datetime.combine(dt.date(year, month, day), base.time()) for day in sorted(set(days))]
            periods.append([candidate for candidate in month_starts if candidate >= base])
    else:  # YEARLY
        for k in range(MAX_PERIODS):
            year = base.year + k * interval
            if base.month == 2 and base.day == 29 and _days_in_month(year, 2) < 29:
                periods.append([])
                continue
            periods.append([dt.datetime.combine(dt.date(year, base.month, base.day), base.time())])
    return periods


def _rrule_starts(rule_text: str, dtstart: Instant, horizon: dt.datetime) -> list[Instant] | None:
    """Expand an RRULE into concrete starts up to ``horizon``; None if unsupported."""
    rule = _parse_rrule(rule_text)
    if not _rrule_supported(rule):
        return None
    count = int(rule["COUNT"]) if "COUNT" in rule else None
    until: dt.datetime | None = None
    if "UNTIL" in rule:
        until_value = parse_instant(rule["UNTIL"], {})
        # A date-only UNTIL is inclusive through the end of that day.
        until = as_utc(until_value) + (dt.timedelta(days=1, seconds=-1) if not isinstance(until_value, dt.datetime) else dt.timedelta())

    all_day = not isinstance(dtstart, dt.datetime)
    if all_day:
        tz: dt.tzinfo | None = None
        base = dt.datetime.combine(dtstart, dt.time())
    else:
        tz = dtstart.tzinfo
        base = dtstart.replace(tzinfo=None)

    def emit(naive: dt.datetime) -> Instant:
        return naive.date() if all_day else naive.replace(tzinfo=tz)

    horizon_utc = as_utc(horizon)
    starts: list[Instant] = []
    done = False
    for period in _candidate_starts(rule, base):
        for naive in period:
            occurrence = emit(naive)
            occurrence_utc = as_utc(occurrence)
            if until is not None and occurrence_utc > until:
                done = True
                break
            if count is not None and len(starts) >= count:
                done = True
                break
            if occurrence_utc >= horizon_utc:
                done = True
                break
            starts.append(occurrence)
            if len(starts) >= MAX_OCCURRENCES:
                done = True
                break
        if done:
            break
    if not starts or as_utc(starts[0]) != as_utc(dtstart):
        # DTSTART always begins the recurrence set, even when the rule pattern skips it.
        starts.insert(0, dtstart)
    return starts


def _occurrence_starts(vevent: Component, horizon: dt.datetime) -> list[Instant]:
    dtstart_prop = first_prop(vevent, "DTSTART")
    if dtstart_prop is None:
        return []
    dtstart = prop_instant(dtstart_prop)
    rrule_prop = first_prop(vevent, "RRULE")
    starts: list[Instant] = [dtstart]
    if rrule_prop is not None:
        expanded = _rrule_starts(rrule_prop.value, dtstart, horizon)
        if expanded is not None:
            starts = expanded
    for rdate in all_props(vevent, "RDATE"):
        for chunk in rdate.value.split(","):
            if chunk.strip():
                starts.append(parse_instant(chunk, rdate.params))
    excluded: set[dt.datetime] = set()
    for exdate in all_props(vevent, "EXDATE"):
        for chunk in exdate.value.split(","):
            if chunk.strip():
                excluded.add(as_utc(parse_instant(chunk, exdate.params)))
    unique: dict[dt.datetime, Instant] = {}
    for start in starts:
        key = as_utc(start)
        if key not in excluded and key not in unique:
            unique[key] = start
    return [unique[key] for key in sorted(unique)]


def _end_of(start: Instant, duration: dt.timedelta) -> Instant:
    return start + duration


def _overlaps(start_utc: dt.datetime, end_utc: dt.datetime, window_start: dt.datetime, window_end: dt.datetime) -> bool:
    if end_utc <= start_utc:
        return window_start <= start_utc < window_end
    return end_utc > window_start and start_utc < window_end


def expand(vcal: Component, window_start: dt.datetime, window_end: dt.datetime) -> list[Occurrence]:
    """Concrete VEVENT occurrences overlapping [window_start, window_end), overrides applied."""
    by_uid: dict[str, list[Component]] = {}
    for vevent in vevents(vcal):
        uid_prop = first_prop(vevent, "UID")
        uid = uid_prop.value if uid_prop is not None else ""
        by_uid.setdefault(uid, []).append(vevent)

    ws_utc, we_utc = as_utc(window_start), as_utc(window_end)
    out: list[Occurrence] = []
    for group in by_uid.values():
        masters = [ev for ev in group if first_prop(ev, "RECURRENCE-ID") is None]
        overrides = [ev for ev in group if first_prop(ev, "RECURRENCE-ID") is not None]
        replaced: set[dt.datetime] = set()
        for override in overrides:
            rid = first_prop(override, "RECURRENCE-ID")
            if rid is not None:
                replaced.add(as_utc(prop_instant(rid)))
        if masters:
            master = masters[0]
            duration = _event_duration(master)
            for start in _occurrence_starts(master, window_end):
                if as_utc(start) in replaced:
                    continue
                end = _end_of(start, duration)
                if _overlaps(as_utc(start), as_utc(end), ws_utc, we_utc):
                    out.append(Occurrence(vevent=master, start=start, end=end))
        for override in overrides:
            dtstart_prop = first_prop(override, "DTSTART")
            if dtstart_prop is None:
                continue
            start = prop_instant(dtstart_prop)
            end = _end_of(start, _event_duration(override))
            if _overlaps(as_utc(start), as_utc(end), ws_utc, we_utc):
                out.append(Occurrence(vevent=override, start=start, end=end))
    out.sort(key=lambda occ: as_utc(occ.start))
    return out
