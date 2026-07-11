#!/usr/bin/env python3
"""Google Calendar commands for the email-client skill.

email-client is a provider-agnostic IMAP/SMTP client, but calendar is
Google-specific. These commands are gated to Google (Gmail) accounts and
reuse the account's STORED Google OAuth token (the same token cache the
mail side keeps, with transparent refresh via ``imap_client``). They talk
to the Google Calendar REST API v3 directly over ``urllib`` to match the
stdlib-only style of the rest of the skill.

Because one Gmail sign-in now also grants the calendar scope (see
``providers.py``), no separate calendar auth is needed: a freshly added
account gets mail + calendar in one consent. Accounts authed before the
calendar scope was added must re-run:

    email-client auth add --account <name> --provider gmail --reauth

Commands (dispatched from ``email-client calendar ...``):

    list-calendars   the account's calendar list
    list             upcoming events (--days-ahead / --days-back window)
    get              a single event by id
    create           create an event (with attendees, invites go out)
    update           patch an event
    delete           delete an event
    respond          accept / decline / tentatively accept an invite

NOTE ON INVITES: creating or updating an event that has attendees causes
Google to email calendar invites/updates to those attendees. That is a
real outward "send", exactly like sending mail. The EMAIL_DRAFT_ONLY guard
is for email sending only and does NOT block calendar writes; use judgment
before creating/updating events with attendees.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

import imap_client

CAL_API_BASE = "https://www.googleapis.com/calendar/v3"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"

RESPONSE_MAP = {
    "accept": "accepted",
    "decline": "declined",
    "tentative": "tentativelyAccepted",
}


# -- account gating + token ----------------------------------------


def _reauth_hint(account: str) -> str:
    return f"email-client auth add --account {account} --provider gmail --reauth"


def google_account_token(account: str | None) -> tuple[str, str]:
    """Resolve a Google account and return ``(account_name, access_token)``.

    Exits with a clear error if the account is not a Google account, or if
    its stored token predates calendar support (lacks the calendar scope).
    """
    acc = imap_client.resolve_account(account)
    name, profile = imap_client.account_profile(acc)
    # In this skill, Google is the only loopback-oauth provider. Microsoft is
    # device-flow; Yahoo/iCloud/Fastmail/generic are app-password. Gate here so
    # non-Google accounts get a clear error instead of a confusing API failure.
    if profile.get("auth_strategy") != "loopback-oauth":
        sys.exit(
            f"calendar is only supported for Google accounts; account {acc!r} "
            f"uses provider {name!r}. Add or select a Gmail account to use calendar."
        )
    tok = imap_client.load_token(acc)
    if tok is None:
        sys.exit(f"no token for account {acc!r}; run 'email-client auth add --account {acc}' first")
    # Google returns the granted scopes in the token response. If we can see
    # them and calendar isn't among them, this is an old mail-only auth: tell
    # the user to re-auth rather than making a call that will 403.
    scope = tok.get("scope")
    if scope and CALENDAR_SCOPE not in scope.split():
        sys.exit(
            f"account {acc!r} was authorized before calendar support (its token "
            f"lacks the calendar scope). Re-auth to grant it:\n  {_reauth_hint(acc)}"
        )
    token = imap_client.get_access_token(acc)
    return acc, token


# -- HTTP layer (single choke point so tests can mock it) ----------


def _http(method: str, url: str, token: str, body: dict | None = None) -> dict:
    """Make one Calendar API request and return parsed JSON ({} if empty).

    All calendar API traffic funnels through here so tests can monkeypatch a
    single function and assert on ``(method, url, body)``.
    """
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace") if hasattr(e, "read") else str(e)
        if e.code in (401, 403) and (
            "insufficient" in detail.lower() or "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in detail
        ):
            sys.exit(
                "Google Calendar refused the request: this account's token lacks "
                "the calendar scope (old mail-only auth). Re-auth to grant it:\n"
                f"  email-client auth add --account <name> --provider gmail --reauth\n"
                f"(details: {detail})"
            )
        sys.exit(f"Google Calendar API error {e.code}: {detail}")


def _url(path: str, params: dict | None = None) -> str:
    url = CAL_API_BASE + path
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)
    return url


# -- time helpers --------------------------------------------------


def _time_window(days_ahead: int, days_back: int) -> tuple[str, str]:
    """Return (timeMin, timeMax) RFC3339 UTC timestamps for the query window."""
    now = dt.datetime.now(dt.timezone.utc)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    time_min = start_of_today - dt.timedelta(days=days_back)
    time_max = start_of_today + dt.timedelta(days=days_ahead + 1)
    return time_min.isoformat().replace("+00:00", "Z"), time_max.isoformat().replace("+00:00", "Z")


def _time_field(value: str, timezone: str) -> dict:
    """Build a Calendar API start/end object.

    A value containing ``T`` is a timed dateTime; otherwise it is an all-day
    date. ``timeZone`` is attached to dateTime values.
    """
    if "T" in value:
        return {"dateTime": value, "timeZone": timezone}
    return {"date": value}


# -- commands ------------------------------------------------------


def cmd_list_calendars(args) -> None:
    _, token = google_account_token(getattr(args, "account", None))
    result = _http("GET", _url("/users/me/calendarList"), token)
    items = result.get("items", [])
    out = [
        {
            "id": c.get("id"),
            "summary": c.get("summary", ""),
            "primary": c.get("primary", False),
            "accessRole": c.get("accessRole", ""),
        }
        for c in items
    ]
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_list(args) -> None:
    _, token = google_account_token(getattr(args, "account", None))
    time_min, time_max = _time_window(args.days_ahead, args.days_back)
    url = _url(
        f"/calendars/{urllib.parse.quote(args.calendar, safe='')}/events",
        {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 250,
        },
    )
    result = _http("GET", url, token)
    events = result.get("items", [])
    out = [
        {
            "id": e.get("id"),
            "summary": e.get("summary", ""),
            "start": e.get("start", {}),
            "end": e.get("end", {}),
            "location": e.get("location"),
            "attendees": [a.get("email") for a in e.get("attendees", [])],
            "status": e.get("status"),
        }
        for e in events
    ]
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_get(args) -> None:
    _, token = google_account_token(getattr(args, "account", None))
    url = _url(f"/calendars/{urllib.parse.quote(args.calendar, safe='')}/events/{urllib.parse.quote(args.id, safe='')}")
    print(json.dumps(_http("GET", url, token), indent=2, ensure_ascii=False))


def _split_attendees(raw: list[str] | None) -> list[str]:
    """Flatten repeated --attendees values, each possibly comma-separated."""
    out: list[str] = []
    for chunk in raw or []:
        out.extend(a.strip() for a in chunk.split(",") if a.strip())
    return out


def cmd_create(args) -> None:
    _, token = google_account_token(getattr(args, "account", None))
    timezone = args.timezone or "UTC"

    start = args.start
    end = args.end
    if not end:
        if "T" in start:
            try:
                end = (dt.datetime.fromisoformat(start) + dt.timedelta(hours=1)).isoformat()
            except ValueError:
                sys.exit(f"could not parse --start {start!r} as ISO datetime; pass --end explicitly")
        else:
            end = (dt.date.fromisoformat(start) + dt.timedelta(days=1)).isoformat()

    event: dict = {
        "summary": args.subject,
        "start": _time_field(start, timezone),
        "end": _time_field(end, timezone),
    }
    # All-day events use an exclusive end date; bump a same-day end by one day.
    if "date" in event["start"] and "date" in event["end"] and event["start"]["date"] == event["end"]["date"]:
        event["end"]["date"] = (dt.date.fromisoformat(event["end"]["date"]) + dt.timedelta(days=1)).isoformat()

    if args.location:
        event["location"] = args.location
    if args.body:
        event["description"] = args.body
    attendees = _split_attendees(args.attendees)
    if attendees:
        event["attendees"] = [{"email": a} for a in attendees]

    # sendUpdates=all so attendees actually receive the invite (outward send).
    url = _url(
        f"/calendars/{urllib.parse.quote(args.calendar, safe='')}/events",
        {"sendUpdates": "all"},
    )
    print(json.dumps(_http("POST", url, token, event), indent=2, ensure_ascii=False))


def cmd_update(args) -> None:
    _, token = google_account_token(getattr(args, "account", None))
    if (args.start is not None or args.end is not None) and not args.timezone:
        sys.exit("--timezone is required when updating --start or --end")
    timezone = args.timezone or "UTC"

    updates: dict = {}
    if args.subject is not None:
        updates["summary"] = args.subject
    if args.start is not None:
        updates["start"] = _time_field(args.start, timezone)
    if args.end is not None:
        updates["end"] = _time_field(args.end, timezone)
    if args.location is not None:
        updates["location"] = args.location
    if args.body is not None:
        updates["description"] = args.body
    attendees = _split_attendees(args.attendees)
    if attendees:
        updates["attendees"] = [{"email": a} for a in attendees]
    if not updates:
        sys.exit("nothing to update; pass at least one of --subject/--start/--end/--location/--body/--attendees")

    url = _url(
        f"/calendars/{urllib.parse.quote(args.calendar, safe='')}/events/{urllib.parse.quote(args.id, safe='')}",
        {"sendUpdates": "all"},
    )
    print(json.dumps(_http("PATCH", url, token, updates), indent=2, ensure_ascii=False))


def cmd_delete(args) -> None:
    _, token = google_account_token(getattr(args, "account", None))
    url = _url(
        f"/calendars/{urllib.parse.quote(args.calendar, safe='')}/events/{urllib.parse.quote(args.id, safe='')}",
        {"sendUpdates": "all"},
    )
    _http("DELETE", url, token)
    print(json.dumps({"status": "deleted", "id": args.id}, indent=2))


def cmd_respond(args) -> None:
    acc, token = google_account_token(getattr(args, "account", None))
    status = RESPONSE_MAP[args.response]
    cal = urllib.parse.quote(args.calendar, safe="")
    eid = urllib.parse.quote(args.id, safe="")

    event = _http("GET", _url(f"/calendars/{cal}/events/{eid}"), token)
    attendees = event.get("attendees", [])
    if not attendees:
        sys.exit(f"event {args.id!r} has no attendees; nothing to respond to")

    user_email = imap_client.account_user(acc)
    found = False
    for a in attendees:
        if a.get("self") or a.get("email", "").lower() == user_email.lower():
            a["responseStatus"] = status
            found = True
            break
    if not found:
        sys.exit(f"you ({user_email}) are not an attendee of event {args.id!r}")

    url = _url(f"/calendars/{cal}/events/{eid}", {"sendUpdates": "all"})
    _http("PATCH", url, token, {"attendees": attendees})
    print(json.dumps({"status": status, "id": args.id}, indent=2))


# -- parser + dispatch ---------------------------------------------


def build_parser(sub) -> None:
    """Attach the ``calendar`` subcommand tree to an argparse subparsers obj."""
    pc = sub.add_parser("calendar", help="Google Calendar (Gmail accounts only)")
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
    c_g.add_argument("--id", required=True, help="event id")
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
    c_u.add_argument("--id", required=True, help="event id")
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
    c_d.add_argument("--id", required=True, help="event id")
    _cal(c_d)
    _acct(c_d)

    c_r = csub.add_parser("respond", help="respond to an invite")
    c_r.add_argument("--id", required=True, help="event id")
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
