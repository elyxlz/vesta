#!/usr/bin/env python3
"""Calendar commands for the email-client skill, over CalDAV.

Works across providers with the account's existing mail credential: Google
(OAuth Bearer; the Calendar REST API is disabled on the reused Thunderbird
Cloud project, but CalDAV rides the same ``.../auth/calendar`` scope and is
the path Thunderbird itself uses), iCloud and Fastmail (HTTP Basic with the
stored app password), and any generic IMAP provider that also runs a CalDAV
server (per-account ``caldav_url`` in config.json). Microsoft accounts have
no CalDAV; those get a clear pointer to the microsoft skill.

The CalDAV protocol (auth, discovery, verbs, UID lookup) lives in
``caldav_client``; iCalendar parse/emit and recurrence expansion live in
``ics``. Event ids are iCalendar UIDs, and recurring events expand into
concrete occurrences in the query window.

Commands (dispatched from ``email-client calendar ...``):

    list-calendars   the account's calendar collections
    list             upcoming events (--days-ahead / --days-back window)
    get              a single event by id
    create           create an event (with attendees, invites go out)
    update           patch an event
    delete           delete an event
    respond          accept / decline / tentatively accept an invite

NOTE ON INVITES: creating or updating an event that has attendees makes the
server email calendar invites/updates to those attendees (CalDAV scheduling;
Google, iCloud, and Fastmail all do this). That is a real outward "send",
exactly like sending mail. The EMAIL_DRAFT_ONLY guard is for email sending
only and does NOT block calendar writes; use judgment before creating or
updating events with attendees.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.parse
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import caldav_client
import ics

RESPONSE_TO_PARTSTAT = {
    "accept": "ACCEPTED",
    "decline": "DECLINED",
    "tentative": "TENTATIVE",
}

PARTSTAT_TO_RESPONSE = {
    "ACCEPTED": "accepted",
    "DECLINED": "declined",
    "TENTATIVE": "tentative",
    "NEEDS-ACTION": "needsAction",
    "DELEGATED": "delegated",
}


# -- time helpers ----------------------------------------------------------


def _window(days_ahead: int, days_back: int) -> tuple[dt.datetime, dt.datetime]:
    now = dt.datetime.now(dt.UTC)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_of_today - dt.timedelta(days=days_back), start_of_today + dt.timedelta(days=days_ahead + 1)


def _zone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        sys.exit(f"invalid timezone {timezone!r}; use IANA names like 'Europe/London' or 'America/New_York'")


def _parse_local(value: str, tz: ZoneInfo) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        sys.exit(f"could not parse {value!r} as an ISO datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def _set_time_prop(vevent: ics.Component, name: str, value: str, tz: ZoneInfo) -> None:
    """Set DTSTART/DTEND from a CLI value: 'T' means timed (stored as a UTC instant,
    so no VTIMEZONE component is needed), a bare date means all-day."""
    if "T" in value:
        ics.set_prop(vevent, name, ics.format_utc(_parse_local(value, tz)))
    else:
        ics.set_prop(vevent, name, ics.format_date(dt.date.fromisoformat(value)), params={"VALUE": "DATE"})


# -- event -> JSON -----------------------------------------------------------


def _time_json(value: ics.Instant) -> dict[str, str]:
    if isinstance(value, dt.datetime):
        zone = value.tzinfo.key if isinstance(value.tzinfo, ZoneInfo) else "UTC"
        return {"dateTime": value.isoformat(), "timeZone": zone}
    return {"date": value.isoformat()}


def _text(vevent: ics.Component, name: str) -> str:
    prop = ics.first_prop(vevent, name)
    return ics.unescape_text(prop.value) if prop is not None else ""


def _clean_addr(value: str) -> str:
    return re.sub(r"^mailto:", "", value, flags=re.IGNORECASE)


def _summary_json(occ: ics.Occurrence) -> dict:
    vevent = occ.vevent
    return {
        "id": _text(vevent, "UID"),
        "summary": _text(vevent, "SUMMARY"),
        "start": _time_json(occ.start),
        "end": _time_json(occ.end),
        "location": _text(vevent, "LOCATION") or None,
        "attendees": [_clean_addr(prop.value) for prop in ics.all_props(vevent, "ATTENDEE")],
        "status": _text(vevent, "STATUS").lower() or None,
    }


def _attendee_json(prop: ics.Prop) -> dict:
    partstat = prop.params["PARTSTAT"].upper() if "PARTSTAT" in prop.params else ""
    if partstat in PARTSTAT_TO_RESPONSE:
        response = PARTSTAT_TO_RESPONSE[partstat]
    else:
        response = partstat.lower() or None
    return {
        "email": _clean_addr(prop.value),
        "displayName": prop.params["CN"].strip('"') if "CN" in prop.params else None,
        "responseStatus": response,
    }


def _detail_json(vevent: ics.Component) -> dict:
    start_prop = ics.first_prop(vevent, "DTSTART")
    end_prop = ics.first_prop(vevent, "DTEND")
    organizer = ics.first_prop(vevent, "ORGANIZER")
    return {
        "id": _text(vevent, "UID"),
        "summary": _text(vevent, "SUMMARY"),
        "start": _time_json(ics.prop_instant(start_prop)) if start_prop is not None else {},
        "end": _time_json(ics.prop_instant(end_prop)) if end_prop is not None else {},
        "location": _text(vevent, "LOCATION") or None,
        "description": _text(vevent, "DESCRIPTION") or None,
        "status": _text(vevent, "STATUS").lower() or None,
        "organizer": _clean_addr(organizer.value) if organizer is not None else None,
        "attendees": [_attendee_json(prop) for prop in ics.all_props(vevent, "ATTENDEE")],
        "recurrence": [f"RRULE:{prop.value}" for prop in ics.all_props(vevent, "RRULE")] or None,
    }


def _master_vevent(vcal: ics.Component, uid: str) -> ics.Component:
    """The master VEVENT (no RECURRENCE-ID) matching ``uid``, with fallbacks."""
    events = ics.vevents(vcal)
    for vevent in events:
        uid_prop = ics.first_prop(vevent, "UID")
        if uid_prop is not None and uid_prop.value == uid and ics.first_prop(vevent, "RECURRENCE-ID") is None:
            return vevent
    for vevent in events:
        if ics.first_prop(vevent, "RECURRENCE-ID") is None:
            return vevent
    if events:
        return events[0]
    sys.exit(f"event {uid!r} not found")


# -- commands -----------------------------------------------------------------


def cmd_list_calendars(args) -> None:
    ctx = caldav_client.caldav_account(args.account)
    out = [{"id": info.id, "summary": info.name, "primary": info.primary} for info in caldav_client.list_calendars(ctx)]
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_list(args) -> None:
    ctx = caldav_client.caldav_account(args.account)
    start, end = _window(args.days_ahead, args.days_back)
    occurrences: list[ics.Occurrence] = []
    for calendar_data in caldav_client.report_events(ctx, args.calendar, start, end):
        try:
            vcal = ics.parse_calendar(calendar_data)
        except ValueError:
            continue
        occurrences.extend(ics.expand(vcal, start, end))
    occurrences.sort(key=lambda occ: ics.as_utc(occ.start))
    print(json.dumps([_summary_json(occ) for occ in occurrences], indent=2, ensure_ascii=False))


def cmd_get(args) -> None:
    ctx = caldav_client.caldav_account(args.account)
    url, text = caldav_client.find_event(ctx, args.calendar, args.id)
    result = _detail_json(_master_vevent(ics.parse_calendar(text), args.id))
    result["ics_href"] = url
    print(json.dumps(result, indent=2, ensure_ascii=False))


def _split_attendees(raw: list[str] | None) -> list[str]:
    """Flatten repeated --attendees values, each possibly comma-separated."""
    out: list[str] = []
    for chunk in raw or []:
        out.extend(addr.strip() for addr in chunk.split(",") if addr.strip())
    return out


def _attendee_prop(email: str) -> ics.Prop:
    return ics.Prop(
        name="ATTENDEE",
        params={"ROLE": "REQ-PARTICIPANT", "PARTSTAT": "NEEDS-ACTION", "RSVP": "TRUE"},
        value=f"mailto:{email}",
    )


def cmd_create(args) -> None:
    ctx = caldav_client.caldav_account(args.account)
    tz = _zone(args.timezone or "UTC")

    start = args.start
    end = args.end
    if not end:
        if "T" in start:
            end = (_parse_local(start, tz) + dt.timedelta(hours=1)).isoformat()
        else:
            end = (dt.date.fromisoformat(start) + dt.timedelta(days=1)).isoformat()
    # All-day events use an exclusive end date; bump a same-day end by one day.
    if "T" not in start and "T" not in end and end == start:
        end = (dt.date.fromisoformat(start) + dt.timedelta(days=1)).isoformat()

    uid = f"{uuid.uuid4().hex}@email-client"
    vevent = ics.Component(name="VEVENT", props=[], children=[])
    ics.set_prop(vevent, "UID", uid)
    ics.set_prop(vevent, "DTSTAMP", ics.format_utc(dt.datetime.now(dt.UTC)))
    ics.set_prop(vevent, "SUMMARY", ics.escape_text(args.subject))
    _set_time_prop(vevent, "DTSTART", start, tz)
    _set_time_prop(vevent, "DTEND", end, tz)
    if args.location:
        ics.set_prop(vevent, "LOCATION", ics.escape_text(args.location))
    if args.body:
        ics.set_prop(vevent, "DESCRIPTION", ics.escape_text(args.body))
    attendees = _split_attendees(args.attendees)
    if attendees:
        vevent.props.extend(_attendee_prop(addr) for addr in attendees)
        ics.set_prop(vevent, "ORGANIZER", f"mailto:{ctx.user}")

    vcal = ics.Component(
        name="VCALENDAR",
        props=[ics.Prop("PRODID", {}, "-//Vesta//email-client//EN"), ics.Prop("VERSION", {}, "2.0")],
        children=[vevent],
    )
    url = caldav_client.collection_url(ctx, args.calendar) + urllib.parse.quote(uid, safe="") + ".ics"
    # If-None-Match: never clobber an existing event of the same id.
    caldav_client.request(
        ctx,
        "PUT",
        url,
        body=ics.serialize(vcal),
        content_type="text/calendar; charset=utf-8",
        extra_headers={"If-None-Match": "*"},
    )
    print(json.dumps({"status": "created", "id": uid, "calendar": args.calendar}, indent=2))


def cmd_update(args) -> None:
    if (args.start is not None or args.end is not None) and not args.timezone:
        sys.exit("--timezone is required when updating --start or --end")
    attendees = _split_attendees(args.attendees)
    if all(value is None for value in (args.subject, args.start, args.end, args.location, args.body)) and not attendees:
        sys.exit("nothing to update; pass at least one of --subject/--start/--end/--location/--body/--attendees")
    ctx = caldav_client.caldav_account(args.account)
    tz = _zone(args.timezone or "UTC")

    url, text = caldav_client.find_event(ctx, args.calendar, args.id)
    vcal = ics.parse_calendar(text)
    vevent = _master_vevent(vcal, args.id)

    if args.subject is not None:
        ics.set_prop(vevent, "SUMMARY", ics.escape_text(args.subject))
    if args.start is not None:
        _set_time_prop(vevent, "DTSTART", args.start, tz)
    if args.end is not None:
        _set_time_prop(vevent, "DTEND", args.end, tz)
    if args.location is not None:
        ics.set_prop(vevent, "LOCATION", ics.escape_text(args.location))
    if args.body is not None:
        ics.set_prop(vevent, "DESCRIPTION", ics.escape_text(args.body))
    if attendees:
        ics.remove_props(vevent, "ATTENDEE")
        vevent.props.extend(_attendee_prop(addr) for addr in attendees)
        if ics.first_prop(vevent, "ORGANIZER") is None:
            ics.set_prop(vevent, "ORGANIZER", f"mailto:{ctx.user}")

    sequence_prop = ics.first_prop(vevent, "SEQUENCE")
    try:
        sequence = int(sequence_prop.value) if sequence_prop is not None else 0
    except ValueError:
        sequence = 0
    ics.set_prop(vevent, "SEQUENCE", str(sequence + 1))
    ics.set_prop(vevent, "DTSTAMP", ics.format_utc(dt.datetime.now(dt.UTC)))

    caldav_client.request(ctx, "PUT", url, body=ics.serialize(vcal), content_type="text/calendar; charset=utf-8")
    print(json.dumps({"status": "updated", "id": args.id, "calendar": args.calendar}, indent=2))


def cmd_delete(args) -> None:
    ctx = caldav_client.caldav_account(args.account)
    url, _ = caldav_client.find_event(ctx, args.calendar, args.id)
    caldav_client.request(ctx, "DELETE", url)
    print(json.dumps({"status": "deleted", "id": args.id}, indent=2))


def cmd_respond(args) -> None:
    ctx = caldav_client.caldav_account(args.account)
    partstat = RESPONSE_TO_PARTSTAT[args.response]

    url, text = caldav_client.find_event(ctx, args.calendar, args.id)
    vcal = ics.parse_calendar(text)
    vevent = _master_vevent(vcal, args.id)

    attendee_props = ics.all_props(vevent, "ATTENDEE")
    if not attendee_props:
        sys.exit(f"event {args.id!r} has no attendees; nothing to respond to")
    me = next((prop for prop in attendee_props if _clean_addr(prop.value).lower() == ctx.user.lower()), None)
    if me is None:
        sys.exit(f"you ({ctx.user}) are not an attendee of event {args.id!r}")
    me.params["PARTSTAT"] = partstat
    ics.set_prop(vevent, "DTSTAMP", ics.format_utc(dt.datetime.now(dt.UTC)))

    caldav_client.request(ctx, "PUT", url, body=ics.serialize(vcal), content_type="text/calendar; charset=utf-8")
    print(json.dumps({"status": PARTSTAT_TO_RESPONSE[partstat], "id": args.id}, indent=2))


# -- parser + dispatch ---------------------------------------------------------


def build_parser(sub) -> None:
    """Attach the ``calendar`` subcommand tree to an argparse subparsers obj."""
    pc = sub.add_parser("calendar", help="calendar over CalDAV (Google, iCloud, Fastmail, any CalDAV server)")
    csub = pc.add_subparsers(dest="calendar_cmd", required=True)

    def _acct(p):
        p.add_argument("--account", default=None, help="account name (defaults to accounts.json default)")

    def _cal(p):
        p.add_argument("--calendar", default="primary", help="calendar id (default: primary)")

    c_lc = csub.add_parser("list-calendars", help="list the account's calendars")
    _acct(c_lc)

    c_l = csub.add_parser("list", help="list upcoming events")
    c_l.add_argument("--days-ahead", type=int, default=7, help="days forward to include (default 7)")
    c_l.add_argument("--days-back", type=int, default=0, help="days back to include (default 0)")
    _cal(c_l)
    _acct(c_l)

    c_g = csub.add_parser("get", help="get one event by id")
    c_g.add_argument("--id", required=True, help="event id (iCalendar UID)")
    _cal(c_g)
    _acct(c_g)

    c_c = csub.add_parser("create", help="create an event (attendees get invites)")
    c_c.add_argument("--subject", required=True, help="event title")
    c_c.add_argument("--start", required=True, help="ISO start, e.g. 2026-07-20T15:00:00 (or a date for all-day)")
    c_c.add_argument("--end", default=None, help="ISO end; defaults to +1h (timed) or +1 day (all-day)")
    c_c.add_argument("--attendees", action="append", default=None, help="attendee email(s), comma-separated or repeated")
    c_c.add_argument("--location", default=None)
    c_c.add_argument("--body", default=None, help="event description")
    c_c.add_argument("--timezone", default=None, help="IANA timezone (default UTC)")
    _cal(c_c)
    _acct(c_c)

    c_u = csub.add_parser("update", help="patch an event (attendees get updates)")
    c_u.add_argument("--id", required=True, help="event id (iCalendar UID)")
    c_u.add_argument("--subject", default=None)
    c_u.add_argument("--start", default=None, help="ISO start (requires --timezone)")
    c_u.add_argument("--end", default=None, help="ISO end (requires --timezone)")
    c_u.add_argument("--attendees", action="append", default=None, help="replace attendee list (comma-separated or repeated)")
    c_u.add_argument("--location", default=None)
    c_u.add_argument("--body", default=None, help="event description")
    c_u.add_argument("--timezone", default=None, help="IANA timezone (required with --start/--end)")
    _cal(c_u)
    _acct(c_u)

    c_d = csub.add_parser("delete", help="delete an event (attendees get cancellations)")
    c_d.add_argument("--id", required=True, help="event id (iCalendar UID)")
    _cal(c_d)
    _acct(c_d)

    c_r = csub.add_parser("respond", help="respond to an invite")
    c_r.add_argument("--id", required=True, help="event id (iCalendar UID)")
    c_r.add_argument("--response", required=True, choices=["accept", "decline", "tentative"])
    _cal(c_r)
    _acct(c_r)


_DISPATCH = {
    "list-calendars": cmd_list_calendars,
    "list": cmd_list,
    "get": cmd_get,
    "create": cmd_create,
    "update": cmd_update,
    "delete": cmd_delete,
    "respond": cmd_respond,
}


def dispatch(args) -> None:
    _DISPATCH[args.calendar_cmd](args)


def main() -> None:
    ap = argparse.ArgumentParser(prog="email-client calendar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    build_parser(sub)
    args = ap.parse_args()
    dispatch(args)


if __name__ == "__main__":
    main()
