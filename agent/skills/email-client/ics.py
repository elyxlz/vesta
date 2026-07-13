#!/usr/bin/env python3
"""Minimal iCalendar engine for the email-client calendar commands.

Parse, edit, and re-serialize VCALENDAR streams and expand recurring events
into concrete occurrences, stdlib only, so the skill's runtime venv needs no
extra packages. Parsing keeps each property's raw value and parameters, so an
event fetched from a server round-trips through an edit without losing
properties this module does not model.

Recurrence support covers what Google, iCloud, Fastmail, and Outlook exports
emit in practice: FREQ daily/weekly/monthly/yearly, INTERVAL, COUNT, UNTIL,
WKST, BYDAY (weekly day lists, monthly/yearly ordinals like 2TU or -1FR),
BYMONTHDAY, BYMONTH (yearly), BYSETPOS, EXDATE, RDATE (including
VALUE=PERIOD), and RECURRENCE-ID overrides. A rule beyond that yields the
master occurrence with the unsupported rule reported on the occurrence, never
a silent partial schedule.

TZID resolution order: IANA zoneinfo, then the CLDR Windows zone-name map,
then a fixed-offset fallback derived from an embedded VTIMEZONE; a TZID that
resolves through none of those is treated as UTC and reported by
:func:`unresolved_tzid` so callers can surface a warning instead of silently
shifting times. Floating date-times (no TZID, no Z) are local per RFC 5545
and interpreted in the process's local timezone.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import re
import typing as tp
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Instant = dt.datetime | dt.date

MAX_OCCURRENCES = 1000
MAX_PERIODS = 5000
FOLD_WIDTH = 74

WEEKDAY_CODES = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
SUPPORTED_RRULE_KEYS = {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY", "BYMONTH", "BYSETPOS", "WKST"}

_MONTHLY_BYDAY_RE = re.compile(r"^([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)$")
_DT_RE = re.compile(r"^(\d{8})(?:T(\d{6})(Z?))?$")
_DURATION_RE = re.compile(r"^([+-]?)P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
_UTC_OFFSET_RE = re.compile(r"^([+-])(\d{2})(\d{2})(\d{2})?$")

# CLDR windowsZones territory-001 defaults: Windows time zone names (what
# Outlook-exported ICS files carry as TZID) mapped to IANA zone names.
WINDOWS_TZID_TO_IANA = {
    "Dateline Standard Time": "Etc/GMT+12",
    "UTC-11": "Etc/GMT+11",
    "Aleutian Standard Time": "America/Adak",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "Marquesas Standard Time": "Pacific/Marquesas",
    "Alaskan Standard Time": "America/Anchorage",
    "UTC-09": "Etc/GMT+9",
    "Pacific Standard Time (Mexico)": "America/Tijuana",
    "UTC-08": "Etc/GMT+8",
    "Pacific Standard Time": "America/Los_Angeles",
    "US Mountain Standard Time": "America/Phoenix",
    "Mountain Standard Time (Mexico)": "America/Mazatlan",
    "Mountain Standard Time": "America/Denver",
    "Yukon Standard Time": "America/Whitehorse",
    "Central America Standard Time": "America/Guatemala",
    "Central Standard Time": "America/Chicago",
    "Easter Island Standard Time": "Pacific/Easter",
    "Central Standard Time (Mexico)": "America/Mexico_City",
    "Canada Central Standard Time": "America/Regina",
    "SA Pacific Standard Time": "America/Bogota",
    "Eastern Standard Time (Mexico)": "America/Cancun",
    "Eastern Standard Time": "America/New_York",
    "Haiti Standard Time": "America/Port-au-Prince",
    "Cuba Standard Time": "America/Havana",
    "US Eastern Standard Time": "America/Indianapolis",
    "Turks And Caicos Standard Time": "America/Grand_Turk",
    "Paraguay Standard Time": "America/Asuncion",
    "Atlantic Standard Time": "America/Halifax",
    "Venezuela Standard Time": "America/Caracas",
    "Central Brazilian Standard Time": "America/Cuiaba",
    "SA Western Standard Time": "America/La_Paz",
    "Pacific SA Standard Time": "America/Santiago",
    "Newfoundland Standard Time": "America/St_Johns",
    "Tocantins Standard Time": "America/Araguaina",
    "E. South America Standard Time": "America/Sao_Paulo",
    "SA Eastern Standard Time": "America/Cayenne",
    "Argentina Standard Time": "America/Buenos_Aires",
    "Montevideo Standard Time": "America/Montevideo",
    "Magallanes Standard Time": "America/Punta_Arenas",
    "Saint Pierre Standard Time": "America/Miquelon",
    "Bahia Standard Time": "America/Bahia",
    "UTC-02": "Etc/GMT+2",
    "Greenland Standard Time": "America/Godthab",
    "Azores Standard Time": "Atlantic/Azores",
    "Cape Verde Standard Time": "Atlantic/Cape_Verde",
    "UTC": "Etc/UTC",
    "GMT Standard Time": "Europe/London",
    "Greenwich Standard Time": "Atlantic/Reykjavik",
    "Sao Tome Standard Time": "Africa/Sao_Tome",
    "Morocco Standard Time": "Africa/Casablanca",
    "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Budapest",
    "Romance Standard Time": "Europe/Paris",
    "Central European Standard Time": "Europe/Warsaw",
    "W. Central Africa Standard Time": "Africa/Lagos",
    "Jordan Standard Time": "Asia/Amman",
    "GTB Standard Time": "Europe/Bucharest",
    "Middle East Standard Time": "Asia/Beirut",
    "Egypt Standard Time": "Africa/Cairo",
    "E. Europe Standard Time": "Europe/Chisinau",
    "Syria Standard Time": "Asia/Damascus",
    "West Bank Standard Time": "Asia/Hebron",
    "South Africa Standard Time": "Africa/Johannesburg",
    "FLE Standard Time": "Europe/Kiev",
    "Israel Standard Time": "Asia/Jerusalem",
    "South Sudan Standard Time": "Africa/Juba",
    "Kaliningrad Standard Time": "Europe/Kaliningrad",
    "Sudan Standard Time": "Africa/Khartoum",
    "Libya Standard Time": "Africa/Tripoli",
    "Namibia Standard Time": "Africa/Windhoek",
    "Arabic Standard Time": "Asia/Baghdad",
    "Turkey Standard Time": "Europe/Istanbul",
    "Arab Standard Time": "Asia/Riyadh",
    "Belarus Standard Time": "Europe/Minsk",
    "Russian Standard Time": "Europe/Moscow",
    "E. Africa Standard Time": "Africa/Nairobi",
    "Volgograd Standard Time": "Europe/Volgograd",
    "Iran Standard Time": "Asia/Tehran",
    "Arabian Standard Time": "Asia/Dubai",
    "Astrakhan Standard Time": "Europe/Astrakhan",
    "Azerbaijan Standard Time": "Asia/Baku",
    "Russia Time Zone 3": "Europe/Samara",
    "Mauritius Standard Time": "Indian/Mauritius",
    "Saratov Standard Time": "Europe/Saratov",
    "Georgian Standard Time": "Asia/Tbilisi",
    "Caucasus Standard Time": "Asia/Yerevan",
    "Afghanistan Standard Time": "Asia/Kabul",
    "West Asia Standard Time": "Asia/Tashkent",
    "Ekaterinburg Standard Time": "Asia/Yekaterinburg",
    "Pakistan Standard Time": "Asia/Karachi",
    "Qyzylorda Standard Time": "Asia/Qyzylorda",
    "India Standard Time": "Asia/Calcutta",
    "Sri Lanka Standard Time": "Asia/Colombo",
    "Nepal Standard Time": "Asia/Katmandu",
    "Central Asia Standard Time": "Asia/Almaty",
    "Bangladesh Standard Time": "Asia/Dhaka",
    "Omsk Standard Time": "Asia/Omsk",
    "Myanmar Standard Time": "Asia/Rangoon",
    "SE Asia Standard Time": "Asia/Bangkok",
    "Altai Standard Time": "Asia/Barnaul",
    "W. Mongolia Standard Time": "Asia/Hovd",
    "North Asia Standard Time": "Asia/Krasnoyarsk",
    "N. Central Asia Standard Time": "Asia/Novosibirsk",
    "Tomsk Standard Time": "Asia/Tomsk",
    "China Standard Time": "Asia/Shanghai",
    "North Asia East Standard Time": "Asia/Irkutsk",
    "Singapore Standard Time": "Asia/Singapore",
    "W. Australia Standard Time": "Australia/Perth",
    "Taipei Standard Time": "Asia/Taipei",
    "Ulaanbaatar Standard Time": "Asia/Ulaanbaatar",
    "Aus Central W. Standard Time": "Australia/Eucla",
    "Transbaikal Standard Time": "Asia/Chita",
    "Tokyo Standard Time": "Asia/Tokyo",
    "North Korea Standard Time": "Asia/Pyongyang",
    "Korea Standard Time": "Asia/Seoul",
    "Yakutsk Standard Time": "Asia/Yakutsk",
    "Cen. Australia Standard Time": "Australia/Adelaide",
    "AUS Central Standard Time": "Australia/Darwin",
    "E. Australia Standard Time": "Australia/Brisbane",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "West Pacific Standard Time": "Pacific/Port_Moresby",
    "Tasmania Standard Time": "Australia/Hobart",
    "Vladivostok Standard Time": "Asia/Vladivostok",
    "Lord Howe Standard Time": "Australia/Lord_Howe",
    "Bougainville Standard Time": "Pacific/Bougainville",
    "Russia Time Zone 10": "Asia/Srednekolymsk",
    "Magadan Standard Time": "Asia/Magadan",
    "Norfolk Standard Time": "Pacific/Norfolk",
    "Sakhalin Standard Time": "Asia/Sakhalin",
    "Central Pacific Standard Time": "Pacific/Guadalcanal",
    "Russia Time Zone 11": "Asia/Kamchatka",
    "New Zealand Standard Time": "Pacific/Auckland",
    "UTC+12": "Etc/GMT-12",
    "Fiji Standard Time": "Pacific/Fiji",
    "Chatham Islands Standard Time": "Pacific/Chatham",
    "UTC+13": "Etc/GMT-13",
    "Tonga Standard Time": "Pacific/Tongatapu",
    "Samoa Standard Time": "Pacific/Apia",
    "Line Islands Standard Time": "Pacific/Kiritimati",
}

TzMap = dict[str, dt.tzinfo]


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
    rrule_unsupported: str | None = None


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
        # Legacy valueless parameters (vCalendar 1.0 style) round-trip as "".
        key, _, value = part.partition("=")
        if key:
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
        head += f";{key}" if value == "" else f";{key}={_param_text(value)}"
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


# -- time zones --------------------------------------------------------------


def _iana_zone(name: str) -> dt.tzinfo | None:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return None


def _local_tz() -> dt.tzinfo:
    """The process's local timezone, used for RFC 5545 floating date-times."""
    return dt.datetime.now().astimezone().tzinfo or dt.UTC


def resolve_zone(tzid: str, tzmap: TzMap | None = None) -> dt.tzinfo | None:
    """Resolve a TZID: IANA name, then Windows zone name, then a VTIMEZONE fallback."""
    name = tzid.strip('"')
    zone = _iana_zone(name)
    if zone is not None:
        return zone
    if name in WINDOWS_TZID_TO_IANA:
        zone = _iana_zone(WINDOWS_TZID_TO_IANA[name])
        if zone is not None:
            return zone
    if tzmap and name in tzmap:
        return tzmap[name]
    return None


def unresolved_tzid(prop: Prop | None, tzmap: TzMap | None = None) -> str | None:
    """The property's TZID when it cannot be resolved to any zone, else None."""
    if prop is None or "TZID" not in prop.params:
        return None
    tzid = prop.params["TZID"].strip('"')
    return tzid if resolve_zone(tzid, tzmap) is None else None


def _parse_utc_offset(value: str) -> dt.timedelta | None:
    match = _UTC_OFFSET_RE.match(value.strip())
    if not match:
        return None
    sign = 1 if match.group(1) == "+" else -1
    hours, minutes = int(match.group(2)), int(match.group(3))
    seconds = int(match.group(4)) if match.group(4) else 0
    return sign * dt.timedelta(hours=hours, minutes=minutes, seconds=seconds)


def _format_utc_offset(delta: dt.timedelta) -> str:
    total = int(delta.total_seconds())
    sign = "+" if total >= 0 else "-"
    hours, remainder = divmod(abs(total), 3600)
    return f"{sign}{hours:02d}{remainder // 60:02d}"


def timezone_map(vcal: Component) -> TzMap:
    """Fixed-offset fallback zones from embedded VTIMEZONEs.

    Used only for TZIDs that are neither IANA nor known Windows names; the
    STANDARD block's TZOFFSETTO becomes a fixed offset (DST shifts within such
    a custom zone are not modeled, which still beats silently assuming UTC).
    """
    out: TzMap = {}
    for child in vcal.children:
        if child.name != "VTIMEZONE":
            continue
        tzid_prop = first_prop(child, "TZID")
        if tzid_prop is None:
            continue
        for block_name in ("STANDARD", "DAYLIGHT"):
            block = next((grand for grand in child.children if grand.name == block_name), None)
            if block is None:
                continue
            offset_prop = first_prop(block, "TZOFFSETTO")
            if offset_prop is None:
                continue
            delta = _parse_utc_offset(offset_prop.value)
            if delta is None:
                continue
            name = tzid_prop.value.strip('"')
            out[name] = dt.timezone(delta, name)
            break
    return out


def build_vtimezone(zone: ZoneInfo, year: int) -> Component:
    """A minimal VTIMEZONE for ``zone`` from zoneinfo transitions around ``year``."""
    samples = [dt.datetime(sample_year, month, 1, tzinfo=dt.UTC) for sample_year in (year, year + 1) for month in range(1, 13)]
    blocks: list[Component] = []
    seen: set[tuple[dt.timedelta, dt.timedelta]] = set()
    for lower, upper in zip(samples, samples[1:]):
        offset_before = lower.astimezone(zone).utcoffset() or dt.timedelta()
        offset_after = upper.astimezone(zone).utcoffset() or dt.timedelta()
        if offset_before == offset_after or (offset_before, offset_after) in seen:
            continue
        seen.add((offset_before, offset_after))
        low, high = lower, upper
        while high - low > dt.timedelta(minutes=1):
            mid = low + (high - low) / 2
            if (mid.astimezone(zone).utcoffset() or dt.timedelta()) == offset_before:
                low = mid
            else:
                high = mid
        local_start = high.astimezone(zone).replace(tzinfo=None)
        blocks.append(
            Component(
                name="DAYLIGHT" if offset_after > offset_before else "STANDARD",
                props=[
                    Prop("DTSTART", {}, local_start.strftime("%Y%m%dT%H%M%S")),
                    Prop("TZOFFSETFROM", {}, _format_utc_offset(offset_before)),
                    Prop("TZOFFSETTO", {}, _format_utc_offset(offset_after)),
                ],
                children=[],
            )
        )
    if not blocks:
        offset = dt.datetime(year, 1, 1, tzinfo=dt.UTC).astimezone(zone).utcoffset() or dt.timedelta()
        blocks.append(
            Component(
                name="STANDARD",
                props=[
                    Prop("DTSTART", {}, "19700101T000000"),
                    Prop("TZOFFSETFROM", {}, _format_utc_offset(offset)),
                    Prop("TZOFFSETTO", {}, _format_utc_offset(offset)),
                ],
                children=[],
            )
        )
    return Component(name="VTIMEZONE", props=[Prop("TZID", {}, zone.key)], children=blocks)


# -- date/time --------------------------------------------------------------


def parse_instant(value: str, params: dict[str, str], tzmap: TzMap | None = None) -> Instant:
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
    if "TZID" in params:
        tz = resolve_zone(params["TZID"], tzmap) or dt.UTC
    else:
        tz = _local_tz()
    return dt.datetime.combine(day, time_of_day, tzinfo=tz)


def prop_instant(prop: Prop, tzmap: TzMap | None = None) -> Instant:
    return parse_instant(prop.value, prop.params, tzmap)


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


def _event_duration(vevent: Component, tzmap: TzMap | None = None) -> dt.timedelta:
    start_prop = first_prop(vevent, "DTSTART")
    if start_prop is None:
        return dt.timedelta()
    start = prop_instant(start_prop, tzmap)
    end_prop = first_prop(vevent, "DTEND")
    if end_prop is not None:
        return as_utc(prop_instant(end_prop, tzmap)) - as_utc(start)
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


def _int_list(value: str) -> list[int]:
    return [int(part) for part in value.split(",") if part.strip()]


def _byday_specs(value: str) -> list[tuple[int | None, int]]:
    """[(ordinal or None, weekday index)] for a BYDAY list (validated upstream)."""
    specs: list[tuple[int | None, int]] = []
    for spec in value.split(","):
        prefix, code = spec[:-2], spec[-2:]
        specs.append((int(prefix) if prefix else None, WEEKDAY_CODES[code]))
    return specs


def _rrule_supported(rule: dict[str, str]) -> bool:
    if "FREQ" not in rule or not SUPPORTED_RRULE_KEYS.issuperset(rule):
        return False
    freq = rule["FREQ"].upper()
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return False
    has_byday = "BYDAY" in rule and rule["BYDAY"]
    has_bymonthday = "BYMONTHDAY" in rule and rule["BYMONTHDAY"]
    has_bymonth = "BYMONTH" in rule and rule["BYMONTH"]
    if has_bymonth and freq != "YEARLY":
        return False
    if has_byday and has_bymonthday:
        return False
    if has_byday:
        if freq == "WEEKLY":
            if not all(code in WEEKDAY_CODES for code in rule["BYDAY"].split(",")):
                return False
        elif freq == "MONTHLY" or (freq == "YEARLY" and has_bymonth):
            if not all(_MONTHLY_BYDAY_RE.match(spec) for spec in rule["BYDAY"].split(",")):
                return False
        else:
            return False
    if has_bymonthday and freq not in ("MONTHLY", "YEARLY"):
        return False
    if has_bymonthday and freq == "YEARLY" and not has_bymonth:
        return False
    try:
        for key in ("COUNT", "INTERVAL"):
            if key in rule:
                int(rule[key])
        for key in ("BYSETPOS", "BYMONTH", "BYMONTHDAY"):
            if key in rule and rule[key]:
                _int_list(rule[key])
    except ValueError:
        return False
    return True


def _rule_interval(rule: dict[str, str]) -> int:
    return int(rule["INTERVAL"]) if "INTERVAL" in rule else 1


def _week_anchor(rule: dict[str, str], base: dt.datetime) -> tuple[dt.datetime, list[int]]:
    """(start of DTSTART's week per WKST, sorted BYDAY offsets from that week start)."""
    wkst = WEEKDAY_CODES[rule["WKST"]] if "WKST" in rule and rule["WKST"] in WEEKDAY_CODES else 0
    week_start = base - dt.timedelta(days=(base.weekday() - wkst) % 7)
    byday = rule["BYDAY"] if "BYDAY" in rule and rule["BYDAY"] else ""
    offsets = sorted({(weekday - wkst) % 7 for _, weekday in _byday_specs(byday)}) if byday else []
    return week_start, offsets


def _month_days(rule: dict[str, str], base: dt.datetime, year: int, month: int) -> list[int]:
    """Days of one month matching BYDAY / BYMONTHDAY (or DTSTART's day)."""
    limit = _days_in_month(year, month)
    if "BYDAY" in rule and rule["BYDAY"]:
        days: set[int] = set()
        for ordinal, weekday in _byday_specs(rule["BYDAY"]):
            matching = [d for d in range(1, limit + 1) if dt.date(year, month, d).weekday() == weekday]
            if ordinal is None:
                days.update(matching)
            elif 0 < ordinal <= len(matching):
                days.add(matching[ordinal - 1])
            elif ordinal < 0 and -ordinal <= len(matching):
                days.add(matching[ordinal])
        return sorted(days)
    monthdays = _int_list(rule["BYMONTHDAY"]) if "BYMONTHDAY" in rule and rule["BYMONTHDAY"] else [base.day]
    resolved = {d if d > 0 else limit + 1 + d for d in monthdays}
    return sorted(d for d in resolved if 1 <= d <= limit)


def _apply_bysetpos(rule: dict[str, str], candidates: list[dt.datetime]) -> list[dt.datetime]:
    if "BYSETPOS" not in rule or not rule["BYSETPOS"] or not candidates:
        return candidates
    picked: set[dt.datetime] = set()
    for pos in _int_list(rule["BYSETPOS"]):
        index = pos - 1 if pos > 0 else len(candidates) + pos
        if 0 <= index < len(candidates):
            picked.add(candidates[index])
    return sorted(picked)


def _period_candidates(rule: dict[str, str], base: dt.datetime, period: int) -> list[dt.datetime]:
    """Naive wall-clock candidates >= base for one period index, ascending."""
    freq = rule["FREQ"].upper()
    interval = _rule_interval(rule)
    if freq == "DAILY":
        candidates = [base + dt.timedelta(days=period * interval)]
    elif freq == "WEEKLY":
        week_start, offsets = _week_anchor(rule, base)
        if offsets:
            candidates = [week_start + dt.timedelta(weeks=period * interval, days=offset) for offset in offsets]
        else:
            candidates = [base + dt.timedelta(weeks=period * interval)]
    elif freq == "MONTHLY":
        year, month = _shift_month(base.year, base.month, period * interval)
        candidates = [dt.datetime.combine(dt.date(year, month, day), base.time()) for day in _month_days(rule, base, year, month)]
    else:  # YEARLY
        year = base.year + period * interval
        if "BYMONTH" in rule and rule["BYMONTH"]:
            candidates = []
            for month in sorted(set(_int_list(rule["BYMONTH"]))):
                if not 1 <= month <= 12:
                    continue
                candidates.extend(dt.datetime.combine(dt.date(year, month, day), base.time()) for day in _month_days(rule, base, year, month))
        elif base.month == 2 and base.day == 29 and _days_in_month(year, 2) < 29:
            candidates = []
        else:
            candidates = [dt.datetime.combine(dt.date(year, base.month, base.day), base.time())]
    return [candidate for candidate in _apply_bysetpos(rule, candidates) if candidate >= base]


def _first_period_for(rule: dict[str, str], base: dt.datetime, floor_naive: dt.datetime) -> int:
    """Period index one before the one containing ``floor_naive`` (clamped to 0).

    Fast-forward for windows far after DTSTART: skips straight to the window
    instead of enumerating years of occurrences. Only used when no COUNT is
    present (COUNT must be counted from DTSTART).
    """
    if floor_naive <= base:
        return 0
    freq = rule["FREQ"].upper()
    interval = _rule_interval(rule)
    if freq == "DAILY":
        period = (floor_naive - base).days // interval
    elif freq == "WEEKLY":
        week_start, _ = _week_anchor(rule, base)
        period = (floor_naive - week_start).days // (7 * interval)
    elif freq == "MONTHLY":
        period = ((floor_naive.year - base.year) * 12 + floor_naive.month - base.month) // interval
    else:  # YEARLY
        period = (floor_naive.year - base.year) // interval
    return max(0, period - 1)


def _rrule_starts(rule_text: str, dtstart: Instant, window_start: dt.datetime, horizon: dt.datetime) -> list[Instant] | None:
    """Expand an RRULE into concrete starts up to ``horizon``; None if unsupported.

    Includes the last occurrence before ``window_start`` (so events spanning
    into the window still show) plus every in-window one. Raises ValueError
    when the rule cannot be expanded within the period guard, rather than
    silently truncating.
    """
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
        floor_naive = window_start.astimezone(dt.UTC).replace(tzinfo=None)
    else:
        tz = dtstart.tzinfo
        base = dtstart.replace(tzinfo=None)
        floor_naive = window_start.astimezone(tz).replace(tzinfo=None)

    def emit(naive: dt.datetime) -> Instant:
        return naive.date() if all_day else naive.replace(tzinfo=tz)

    start_period = 0 if count is not None else _first_period_for(rule, base, floor_naive)

    def candidates() -> tp.Iterator[dt.datetime]:
        # DTSTART always begins the recurrence set (RFC 5545), even when the
        # rule pattern skips it; it must count toward COUNT like any occurrence.
        emitted_any = False
        for period in range(start_period, start_period + MAX_PERIODS):
            for naive in _period_candidates(rule, base, period):
                if not emitted_any:
                    emitted_any = True
                    if naive != base:
                        yield base
                yield naive

    floor_utc = as_utc(window_start)
    horizon_utc = as_utc(horizon)
    starts: list[Instant] = []
    last_before: Instant | None = None
    generated = 0
    completed = False
    for naive in candidates():
        occurrence = emit(naive)
        occurrence_utc = as_utc(occurrence)
        if until is not None and occurrence_utc > until:
            completed = True
            break
        generated += 1
        if count is not None and generated > count:
            completed = True
            break
        if occurrence_utc >= horizon_utc:
            completed = True
            break
        if occurrence_utc < floor_utc:
            last_before = occurrence
            continue
        starts.append(occurrence)
        if len(starts) >= MAX_OCCURRENCES:
            completed = True
            break
    if not completed and (count is None or generated < count):
        raise ValueError(f"recurrence too deep to expand (over {MAX_PERIODS} periods): {rule_text}")
    if last_before is not None:
        starts.insert(0, last_before)
    return starts


def _occurrence_starts(
    vevent: Component, window_start: dt.datetime, horizon: dt.datetime, tzmap: TzMap | None = None
) -> tuple[list[tuple[Instant, Instant | None]], str | None]:
    """Deduplicated, sorted (start, end-override) pairs plus the RRULE text when unsupported.

    End overrides come from RDATE periods; everywhere else the end is None and
    the caller applies the master event's duration.
    """
    dtstart_prop = first_prop(vevent, "DTSTART")
    if dtstart_prop is None:
        return [], None
    dtstart = prop_instant(dtstart_prop, tzmap)
    rrule_prop = first_prop(vevent, "RRULE")
    starts: list[Instant] = [dtstart]
    unsupported: str | None = None
    if rrule_prop is not None:
        expanded = _rrule_starts(rrule_prop.value, dtstart, window_start, horizon)
        if expanded is None:
            unsupported = rrule_prop.value
        else:
            starts = expanded
    period_ends: dict[dt.datetime, Instant] = {}
    for rdate in all_props(vevent, "RDATE"):
        for chunk in rdate.value.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "/" in chunk:
                start_text, _, end_text = chunk.partition("/")
                start_value = parse_instant(start_text, rdate.params, tzmap)
                if end_text.lstrip("+-").startswith("P"):
                    end_value: Instant = start_value + _parse_duration(end_text)
                else:
                    end_value = parse_instant(end_text, rdate.params, tzmap)
                starts.append(start_value)
                period_ends[as_utc(start_value)] = end_value
            else:
                starts.append(parse_instant(chunk, rdate.params, tzmap))
    excluded: set[dt.datetime] = set()
    for exdate in all_props(vevent, "EXDATE"):
        for chunk in exdate.value.split(","):
            if chunk.strip():
                excluded.add(as_utc(parse_instant(chunk, exdate.params, tzmap)))
    unique: dict[dt.datetime, Instant] = {}
    for start in starts:
        key = as_utc(start)
        if key not in excluded and key not in unique:
            unique[key] = start
    pairs = [(unique[key], period_ends[key] if key in period_ends else None) for key in sorted(unique)]
    return pairs, unsupported


def _overlaps(start_utc: dt.datetime, end_utc: dt.datetime, window_start: dt.datetime, window_end: dt.datetime) -> bool:
    if end_utc <= start_utc:
        return window_start <= start_utc < window_end
    return end_utc > window_start and start_utc < window_end


def expand(vcal: Component, window_start: dt.datetime, window_end: dt.datetime) -> list[Occurrence]:
    """Concrete VEVENT occurrences overlapping [window_start, window_end), overrides applied."""
    tzmap = timezone_map(vcal)
    by_uid: dict[str, list[Component]] = {}
    for index, vevent in enumerate(vevents(vcal)):
        uid_prop = first_prop(vevent, "UID")
        # UID-less events each get a synthetic key so none shadow another.
        uid = uid_prop.value if uid_prop is not None and uid_prop.value else f"__uid_missing_{index}"
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
                replaced.add(as_utc(prop_instant(rid, tzmap)))
        if masters:
            master = masters[0]
            duration = _event_duration(master, tzmap)
            pairs, unsupported = _occurrence_starts(master, window_start, window_end, tzmap)
            for start, end_override in pairs:
                if as_utc(start) in replaced:
                    continue
                end = end_override if end_override is not None else start + duration
                if _overlaps(as_utc(start), as_utc(end), ws_utc, we_utc):
                    out.append(Occurrence(vevent=master, start=start, end=end, rrule_unsupported=unsupported))
        for override in overrides:
            dtstart_prop = first_prop(override, "DTSTART")
            if dtstart_prop is None:
                continue
            start = prop_instant(dtstart_prop, tzmap)
            end = start + _event_duration(override, tzmap)
            if _overlaps(as_utc(start), as_utc(end), ws_utc, we_utc):
                out.append(Occurrence(vevent=override, start=start, end=end))
    out.sort(key=lambda occ: as_utc(occ.start))
    return out
