"""Calendar over CalDAV: command routing, provider auth selection, iCalendar handling.

calendar_client/caldav_client import imap_client (which needs imap_tools from
the on-box runtime), so a minimal imap_tools stub is registered first. All
network traffic funnels through ``caldav_client.request``, so most tests
monkeypatch that single choke point and feed real multistatus/iCalendar
bodies; the redirect test fakes ``urllib`` one level lower.
"""

import argparse
import datetime as dt
import io
import json
import pathlib
import sys
import types
import urllib.error

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def _install_stubs():
    """Register a minimal fake imap_tools so imap_client imports."""
    if "imap_tools" not in sys.modules:
        it = types.ModuleType("imap_tools")

        def AND(*a, **k):  # noqa: N802 (mirrors imap_tools API name)
            return None

        class MailBox:  # pragma: no cover (never instantiated in these tests)
            pass

        class MailMessageFlags:
            DRAFT = "\\Draft"
            SEEN = "\\Seen"
            ANSWERED = "\\Answered"
            FLAGGED = "\\Flagged"

        it.AND = AND
        it.MailBox = MailBox
        it.MailMessageFlags = MailMessageFlags
        sys.modules["imap_tools"] = it


_install_stubs()
import caldav_client  # noqa: E402
import calendar_client  # noqa: E402
import ics  # noqa: E402
import imap_client  # noqa: E402
import providers  # noqa: E402

GOOGLE_BASE = "https://apidata.googleusercontent.com/caldav/v2"


# -- harness -------------------------------------------------------


def _parse(argv):
    """Route argv through the real parser tree, exactly as email-client does."""
    ap = argparse.ArgumentParser(prog="email-client")
    sub = ap.add_subparsers(dest="cmd", required=True)
    calendar_client.build_parser(sub)
    return ap.parse_args(argv)


def _run(argv, capsys):
    calendar_client.dispatch(_parse(argv))
    return capsys.readouterr().out


def _ctx(auth="bearer", base_url=GOOGLE_BASE, user="me@gmail.com"):
    return caldav_client.CalDavAccount(account="personal", user=user, base_url=base_url, auth=auth)


class _Recorder:
    """Capture caldav_client.request calls and feed canned responses.

    ``responses`` is a list of (method, url_substring, (status, body)) rules;
    the first match wins. Unmatched calls return an empty 207.
    """

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or []

    def __call__(self, ctx, method, url, *, body=None, depth=None, content_type="", extra_headers=None, allow_missing=False):
        self.calls.append({"method": method, "url": url, "body": body, "depth": depth, "extra_headers": extra_headers})
        for rule_method, needle, response in self.responses:
            if rule_method == method and needle in url:
                status, text = response
                return status, text, url
        return 207, "", url


@pytest.fixture
def rec(monkeypatch):
    """Bypass account plumbing (google/bearer ctx); record CalDAV requests."""
    monkeypatch.setattr(caldav_client, "caldav_account", lambda account: _ctx())
    recorder = _Recorder()
    monkeypatch.setattr(caldav_client, "request", recorder)
    return recorder


# -- fixtures: multistatus + ics bodies -----------------------------


MULTISTATUS = """<?xml version="1.0" encoding="UTF-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:caldav="urn:ietf:params:xml:ns:caldav">
 <D:response>
  <D:href>/caldav/v2/me%40gmail.com/events/evt-timed%40google.com.ics</D:href>
  <D:propstat>
   <D:status>HTTP/1.1 200 OK</D:status>
   <D:prop>
    <D:getetag>"111"</D:getetag>
    <caldav:calendar-data>BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART;TZID=Europe/Rome:20260714T100000
DTEND;TZID=Europe/Rome:20260714T110000
UID:evt-timed@google.com
SUMMARY:Lunch with a very long title that Google would fold across lines ok
 ay
LOCATION:Roma
ATTENDEE;PARTSTAT=ACCEPTED;CN=Me:mailto:me@gmail.com
ATTENDEE;PARTSTAT=NEEDS-ACTION;CN=Bob:mailto:bob@example.com
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR
</caldav:calendar-data>
   </D:prop>
  </D:propstat>
 </D:response>
 <D:response>
  <D:href>/caldav/v2/me%40gmail.com/events/evt-allday.ics</D:href>
  <D:propstat>
   <D:status>HTTP/1.1 200 OK</D:status>
   <D:prop>
    <caldav:calendar-data>BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART;VALUE=DATE:20260715
DTEND;VALUE=DATE:20260716
UID:evt-allday
SUMMARY:Public holiday
END:VEVENT
END:VCALENDAR
</caldav:calendar-data>
   </D:prop>
  </D:propstat>
 </D:response>
 <D:response>
  <D:href>/caldav/v2/me%40gmail.com/events/evt-weekly.ics</D:href>
  <D:propstat>
   <D:status>HTTP/1.1 200 OK</D:status>
   <D:prop>
    <caldav:calendar-data>BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART:20260713T090000Z
DTEND:20260713T091500Z
UID:evt-weekly
SUMMARY:Standup
RRULE:FREQ=DAILY;COUNT=5
END:VEVENT
END:VCALENDAR
</caldav:calendar-data>
   </D:prop>
  </D:propstat>
 </D:response>
</D:multistatus>
"""

EXISTING_ICS = "\r\n".join(
    [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "BEGIN:VEVENT",
        "DTSTART:20260720T140000Z",
        "DTEND:20260720T150000Z",
        "UID:evt-timed@google.com",
        "SUMMARY:Old title",
        "SEQUENCE:2",
        "X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:AUTOMATIC",
        "ATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:me@gmail.com",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
)


def _freeze_window(monkeypatch):
    """Pin the query window so the recurring fixture expands deterministically."""

    def fake_window(days_ahead, days_back):
        start = dt.datetime(2026, 7, 13, tzinfo=dt.UTC) - dt.timedelta(days=days_back)
        return start, dt.datetime(2026, 7, 13, tzinfo=dt.UTC) + dt.timedelta(days=days_ahead + 1)

    monkeypatch.setattr(calendar_client, "_window", fake_window)


# -- provider auth selection ----------------------------------------


def _fake_account(monkeypatch, profile, token=None, user="me@example.com"):
    monkeypatch.setattr(imap_client, "resolve_account", lambda a: "acct")
    monkeypatch.setattr(imap_client, "account_profile", lambda a: ("prov", profile))
    monkeypatch.setattr(imap_client, "load_token", lambda a: token)
    monkeypatch.setattr(imap_client, "account_user", lambda a: user)


def test_gmail_account_resolves_to_bearer(monkeypatch):
    profile = {"auth_strategy": "loopback-oauth", "caldav_url": GOOGLE_BASE}
    token = {"scope": "https://mail.google.com/ https://www.googleapis.com/auth/calendar"}
    _fake_account(monkeypatch, profile, token=token, user="me@gmail.com")
    ctx = caldav_client.caldav_account("acct")
    assert ctx.auth == "bearer"
    assert ctx.base_url == GOOGLE_BASE
    assert ctx.user == "me@gmail.com"


def test_gmail_token_without_calendar_scope_tells_user_to_reauth(monkeypatch):
    profile = {"auth_strategy": "loopback-oauth", "caldav_url": GOOGLE_BASE}
    _fake_account(monkeypatch, profile, token={"scope": "https://mail.google.com/"})
    with pytest.raises(SystemExit) as ei:
        caldav_client.caldav_account("acct")
    assert "--reauth" in str(ei.value)


def test_gmail_token_without_scope_field_is_not_blocked(monkeypatch):
    profile = {"auth_strategy": "loopback-oauth", "caldav_url": GOOGLE_BASE}
    _fake_account(monkeypatch, profile, token={"access_token": "x"})
    assert caldav_client.caldav_account("acct").auth == "bearer"


def test_app_password_account_resolves_to_basic(monkeypatch):
    profile = {"auth_strategy": "app-password", "caldav_url": "https://caldav.icloud.com"}
    _fake_account(monkeypatch, profile, user="me@icloud.com")
    ctx = caldav_client.caldav_account("acct")
    assert ctx.auth == "basic"
    assert ctx.base_url == "https://caldav.icloud.com"


def test_microsoft_account_points_at_microsoft_skill(monkeypatch):
    _fake_account(monkeypatch, {"auth_strategy": "device-flow"})
    with pytest.raises(SystemExit) as ei:
        caldav_client.caldav_account("acct")
    assert "no CalDAV calendar for this provider" in str(ei.value)
    assert "microsoft skill" in str(ei.value)


def test_provider_without_caldav_url_errors_with_config_hint(monkeypatch, tmp_path):
    _fake_account(monkeypatch, {"auth_strategy": "app-password"})
    monkeypatch.setattr(imap_client, "account_dir", lambda a: tmp_path)
    with pytest.raises(SystemExit) as ei:
        caldav_client.caldav_account("acct")
    assert "caldav_url" in str(ei.value)


def test_per_account_caldav_url_override_layers_from_config(monkeypatch, tmp_path):
    monkeypatch.setenv("EMAIL_CLIENT_DIR", str(tmp_path))
    (tmp_path / "accounts.json").write_text(json.dumps({"accounts": ["selfhosted"], "default": "selfhosted"}))
    acct_dir = tmp_path / "accounts" / "selfhosted"
    acct_dir.mkdir(parents=True)
    (acct_dir / "config.json").write_text(
        json.dumps({"user": "me@example.org", "provider": "generic", "caldav_url": "https://dav.example.org/dav"})
    )
    _, profile = imap_client.account_profile("selfhosted")
    assert profile["caldav_url"] == "https://dav.example.org/dav"


def test_builtin_profiles_carry_caldav_endpoints():
    assert providers.PROVIDERS["gmail"]["caldav_url"] == GOOGLE_BASE
    assert providers.PROVIDERS["icloud-app-password"]["caldav_url"] == "https://caldav.icloud.com"
    assert providers.PROVIDERS["fastmail-app-password"]["caldav_url"] == "https://caldav.fastmail.com"
    assert "caldav_url" not in providers.PROVIDERS["microsoft-personal"]
    assert "caldav_url" not in providers.PROVIDERS["generic"]


def test_auth_header_bearer_and_basic(monkeypatch):
    monkeypatch.setattr(imap_client, "get_access_token", lambda account: "TOKEN123")
    monkeypatch.setattr(imap_client, "get_app_password", lambda account: "app-pass")
    assert caldav_client._auth_header(_ctx()) == "Bearer TOKEN123"
    basic = caldav_client._auth_header(_ctx(auth="basic", base_url="https://caldav.icloud.com", user="me@icloud.com"))
    assert basic.startswith("Basic ")
    import base64

    assert base64.b64decode(basic.split()[1]).decode() == "me@icloud.com:app-pass"


# -- list ------------------------------------------------------------


def test_list_reports_time_range_on_google_collection(rec, monkeypatch, capsys):
    _freeze_window(monkeypatch)
    rec.responses = [("REPORT", "/events/", (207, MULTISTATUS))]
    _run(["calendar", "list", "--days-ahead", "10", "--days-back", "5"], capsys)
    call = rec.calls[0]
    assert call["method"] == "REPORT"
    assert call["url"] == f"{GOOGLE_BASE}/me@gmail.com/events/"
    assert call["depth"] == "1"
    assert "time-range" in call["body"]
    assert 'name="VEVENT"' in call["body"]


def test_list_parses_timed_all_day_and_folded_summary(rec, monkeypatch, capsys):
    _freeze_window(monkeypatch)
    rec.responses = [("REPORT", "/events/", (207, MULTISTATUS))]
    out = json.loads(_run(["calendar", "list", "--days-ahead", "10"], capsys))

    timed = next(e for e in out if e["id"] == "evt-timed@google.com")
    assert timed["summary"] == "Lunch with a very long title that Google would fold across lines okay"
    assert timed["start"]["dateTime"].startswith("2026-07-14T10:00:00")
    assert timed["start"]["timeZone"] == "Europe/Rome"
    assert timed["location"] == "Roma"
    assert timed["attendees"] == ["me@gmail.com", "bob@example.com"]
    assert timed["status"] == "confirmed"

    allday = next(e for e in out if e["id"] == "evt-allday")
    assert allday["start"] == {"date": "2026-07-15"}
    assert "dateTime" not in allday["start"]


def test_list_expands_recurring_into_occurrences(rec, monkeypatch, capsys):
    _freeze_window(monkeypatch)
    rec.responses = [("REPORT", "/events/", (207, MULTISTATUS))]
    out = json.loads(_run(["calendar", "list", "--days-ahead", "10"], capsys))
    standups = [e for e in out if e["id"] == "evt-weekly"]
    # DAILY;COUNT=5 from 2026-07-13 -> five concrete occurrences in-window.
    assert len(standups) == 5
    starts = sorted(e["start"]["dateTime"] for e in standups)
    assert starts[0].startswith("2026-07-13T09:00:00")
    assert starts[-1].startswith("2026-07-17T09:00:00")


def test_list_custom_calendar_id_used_verbatim_on_google(rec, monkeypatch, capsys):
    _freeze_window(monkeypatch)
    rec.responses = [("REPORT", "/events/", (207, MULTISTATUS))]
    _run(["calendar", "list", "--calendar", "team@group.calendar.google.com"], capsys)
    assert rec.calls[0]["url"] == f"{GOOGLE_BASE}/team@group.calendar.google.com/events/"


# -- list-calendars ---------------------------------------------------


GOOGLE_HOME = """<D:multistatus xmlns:D="DAV:" xmlns:caldav="urn:ietf:params:xml:ns:caldav">
 <D:response>
  <D:href>/caldav/v2/me%40gmail.com/events/</D:href>
  <D:propstat><D:status>HTTP/1.1 200 OK</D:status>
   <D:prop><D:displayname>Me</D:displayname>
    <D:resourcetype><D:collection/><caldav:calendar/></D:resourcetype></D:prop></D:propstat>
 </D:response>
 <D:response>
  <D:href>/caldav/v2/team%40group.calendar.google.com/events/</D:href>
  <D:propstat><D:status>HTTP/1.1 200 OK</D:status>
   <D:prop><D:displayname>Team</D:displayname>
    <D:resourcetype><D:collection/><caldav:calendar/></D:resourcetype></D:prop></D:propstat>
 </D:response>
</D:multistatus>"""


def test_list_calendars_google_marks_primary(rec, capsys):
    rec.responses = [("PROPFIND", "/caldav/v2/", (207, GOOGLE_HOME))]
    out = json.loads(_run(["calendar", "list-calendars", "--account", "personal"], capsys))
    assert rec.calls[0]["url"] == f"{GOOGLE_BASE}/me@gmail.com/"
    assert {"id": "me@gmail.com", "summary": "Me", "primary": True} in out
    assert {"id": "team@group.calendar.google.com", "summary": "Team", "primary": False} in out


ICLOUD_PRINCIPAL = """<D:multistatus xmlns:D="DAV:">
 <D:response><D:href>/</D:href>
  <D:propstat><D:status>HTTP/1.1 200 OK</D:status>
   <D:prop><D:current-user-principal><D:href>/12345/principal/</D:href></D:current-user-principal></D:prop>
  </D:propstat></D:response>
</D:multistatus>"""

ICLOUD_HOME_SET = """<D:multistatus xmlns:D="DAV:" xmlns:caldav="urn:ietf:params:xml:ns:caldav">
 <D:response><D:href>/12345/principal/</D:href>
  <D:propstat><D:status>HTTP/1.1 200 OK</D:status>
   <D:prop><caldav:calendar-home-set><D:href>https://p42-caldav.icloud.com/12345/calendars/</D:href></caldav:calendar-home-set></D:prop>
  </D:propstat></D:response>
</D:multistatus>"""

ICLOUD_CALENDARS = """<D:multistatus xmlns:D="DAV:" xmlns:caldav="urn:ietf:params:xml:ns:caldav">
 <D:response><D:href>/12345/calendars/</D:href>
  <D:propstat><D:status>HTTP/1.1 200 OK</D:status>
   <D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop></D:propstat>
 </D:response>
 <D:response><D:href>/12345/calendars/home/</D:href>
  <D:propstat><D:status>HTTP/1.1 200 OK</D:status>
   <D:prop><D:displayname>Home</D:displayname>
    <D:resourcetype><D:collection/><caldav:calendar/></D:resourcetype>
    <caldav:supported-calendar-component-set><caldav:comp name="VEVENT"/></caldav:supported-calendar-component-set>
   </D:prop></D:propstat>
 </D:response>
 <D:response><D:href>/12345/calendars/reminders/</D:href>
  <D:propstat><D:status>HTTP/1.1 200 OK</D:status>
   <D:prop><D:displayname>Reminders</D:displayname>
    <D:resourcetype><D:collection/><caldav:calendar/></D:resourcetype>
    <caldav:supported-calendar-component-set><caldav:comp name="VTODO"/></caldav:supported-calendar-component-set>
   </D:prop></D:propstat>
 </D:response>
</D:multistatus>"""


def _icloud_recorder():
    # First match wins, so the more specific paths come before the bare host.
    return _Recorder(
        responses=[
            ("PROPFIND", "/12345/principal/", (207, ICLOUD_HOME_SET)),
            ("PROPFIND", "/12345/calendars/", (207, ICLOUD_CALENDARS)),
            ("PROPFIND", "caldav.icloud.com/", (207, ICLOUD_PRINCIPAL)),
        ]
    )


def test_list_calendars_discovers_icloud_home_and_filters_vtodo(monkeypatch, capsys):
    monkeypatch.setattr(
        caldav_client, "caldav_account", lambda a: _ctx(auth="basic", base_url="https://caldav.icloud.com", user="me@icloud.com")
    )
    recorder = _icloud_recorder()
    monkeypatch.setattr(caldav_client, "request", recorder)
    out = json.loads(_run(["calendar", "list-calendars"], capsys))
    assert out == [{"id": "home", "summary": "Home", "primary": True}]
    # Discovery walked principal -> home-set -> partition-host calendars.
    assert recorder.calls[1]["url"] == "https://caldav.icloud.com/12345/principal/"
    assert recorder.calls[2]["url"] == "https://p42-caldav.icloud.com/12345/calendars/"


def test_event_ops_use_discovered_collection(monkeypatch, capsys):
    monkeypatch.setattr(
        caldav_client, "caldav_account", lambda a: _ctx(auth="basic", base_url="https://caldav.icloud.com", user="me@gmail.com")
    )
    recorder = _icloud_recorder()
    recorder.responses.append(("GET", "/calendars/home/", (200, EXISTING_ICS)))
    monkeypatch.setattr(caldav_client, "request", recorder)
    out = json.loads(_run(["calendar", "get", "--id", "evt-timed@google.com"], capsys))
    assert out["summary"] == "Old title"
    get = next(c for c in recorder.calls if c["method"] == "GET")
    assert get["url"] == "https://p42-caldav.icloud.com/12345/calendars/home/evt-timed%40google.com.ics"


# -- get ---------------------------------------------------------------


def test_get_event_by_uid_resource_name(rec, capsys):
    rec.responses = [("GET", "/events/evt-timed%40google.com.ics", (200, EXISTING_ICS))]
    out = json.loads(_run(["calendar", "get", "--id", "evt-timed@google.com"], capsys))
    assert out["id"] == "evt-timed@google.com"
    assert out["summary"] == "Old title"
    assert out["start"] == {"dateTime": "2026-07-20T14:00:00+00:00", "timeZone": "UTC"}
    assert out["attendees"][0]["email"] == "me@gmail.com"
    assert out["attendees"][0]["responseStatus"] == "needsAction"


def test_get_falls_back_to_uid_report_when_resource_name_differs(rec, capsys):
    report_body = f"""<D:multistatus xmlns:D="DAV:" xmlns:caldav="urn:ietf:params:xml:ns:caldav">
     <D:response><D:href>/caldav/v2/me%40gmail.com/events/ABC123.ics</D:href>
      <D:propstat><D:status>HTTP/1.1 200 OK</D:status>
       <D:prop><caldav:calendar-data>{EXISTING_ICS}</caldav:calendar-data></D:prop></D:propstat>
     </D:response></D:multistatus>"""
    rec.responses = [
        ("GET", ".ics", (404, "not found")),
        ("REPORT", "/events/", (207, report_body)),
    ]
    out = json.loads(_run(["calendar", "get", "--id", "evt-timed@google.com"], capsys))
    assert out["summary"] == "Old title"
    report = next(c for c in rec.calls if c["method"] == "REPORT")
    assert "evt-timed@google.com" in report["body"]
    assert 'prop-filter name="UID"' in report["body"]
    assert out["ics_href"] == f"{GOOGLE_BASE}/me%40gmail.com/events/ABC123.ics"


# -- create ------------------------------------------------------------


def test_create_puts_utc_ical_with_attendees(rec, capsys):
    out = json.loads(
        _run(
            [
                "calendar",
                "create",
                "--subject",
                "Sync; agenda, notes",
                "--start",
                "2026-07-20T15:00:00",
                "--end",
                "2026-07-20T16:00:00",
                "--attendees",
                "a@x.com,b@y.com",
                "--attendees",
                "c@z.com",
                "--location",
                "Room 1",
                "--timezone",
                "Europe/London",
            ],
            capsys,
        )
    )
    put = rec.calls[0]
    assert put["method"] == "PUT"
    assert put["url"] == f"{GOOGLE_BASE}/me@gmail.com/events/" + out["id"].replace("@", "%40") + ".ics"
    assert put["extra_headers"] == {"If-None-Match": "*"}
    body = put["body"]
    assert "SUMMARY:Sync\\; agenda\\, notes" in body
    # 15:00 London (BST, UTC+1) -> 14:00 UTC, emitted as a Z time (no VTIMEZONE).
    assert "DTSTART:20260720T140000Z" in body
    assert "DTEND:20260720T150000Z" in body
    assert "ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:a@x.com" in body.replace("\r\n ", "")
    assert "mailto:c@z.com" in body.replace("\r\n ", "")
    assert "ORGANIZER:mailto:me@gmail.com" in body
    assert out["status"] == "created"
    assert out["id"].endswith("@email-client")


def test_create_defaults_end_to_plus_one_hour(rec, capsys):
    _run(["calendar", "create", "--subject", "Quick", "--start", "2026-07-20T09:00:00"], capsys)
    body = rec.calls[0]["body"]
    assert "DTSTART:20260720T090000Z" in body  # default timezone UTC
    assert "DTEND:20260720T100000Z" in body


def test_create_all_day_uses_exclusive_end_date(rec, capsys):
    _run(["calendar", "create", "--subject", "Holiday", "--start", "2026-12-25"], capsys)
    body = rec.calls[0]["body"]
    assert "DTSTART;VALUE=DATE:20261225" in body
    # all-day end date is exclusive => next day
    assert "DTEND;VALUE=DATE:20261226" in body


def test_create_rejects_bad_timezone(rec, capsys):
    with pytest.raises(SystemExit) as ei:
        _run(["calendar", "create", "--subject", "x", "--start", "2026-07-20T10:00:00", "--timezone", "Mars/Phobos"], capsys)
    assert "invalid timezone" in str(ei.value)


# -- update / delete / respond ------------------------------------------


def test_update_patches_summary_and_bumps_sequence(rec, capsys):
    rec.responses = [("GET", ".ics", (200, EXISTING_ICS))]
    _run(["calendar", "update", "--id", "evt-timed@google.com", "--subject", "New title"], capsys)
    put = next(c for c in rec.calls if c["method"] == "PUT")
    assert "SUMMARY:New title" in put["body"]
    assert "SEQUENCE:3" in put["body"]
    # Properties this module does not model survive the round-trip untouched.
    assert "X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:AUTOMATIC" in put["body"]


def test_update_start_requires_timezone(rec, capsys):
    with pytest.raises(SystemExit) as ei:
        _run(["calendar", "update", "--id", "evt1", "--start", "2026-07-20T10:00:00"], capsys)
    assert "timezone" in str(ei.value).lower()


def test_update_with_no_fields_errors(rec, capsys):
    with pytest.raises(SystemExit) as ei:
        _run(["calendar", "update", "--id", "evt1"], capsys)
    assert "nothing to update" in str(ei.value).lower()


def test_update_start_rewrites_dtstart_in_utc(rec, capsys):
    rec.responses = [("GET", ".ics", (200, EXISTING_ICS))]
    _run(
        ["calendar", "update", "--id", "evt-timed@google.com", "--start", "2026-07-21T10:00:00", "--timezone", "Europe/London"],
        capsys,
    )
    put = next(c for c in rec.calls if c["method"] == "PUT")
    assert "DTSTART:20260721T090000Z" in put["body"]


def test_update_replaces_attendees(rec, capsys):
    rec.responses = [("GET", ".ics", (200, EXISTING_ICS))]
    _run(["calendar", "update", "--id", "evt-timed@google.com", "--attendees", "new@x.com"], capsys)
    put = next(c for c in rec.calls if c["method"] == "PUT")
    assert "mailto:new@x.com" in put["body"].replace("\r\n ", "")
    assert "mailto:me@gmail.com" not in put["body"].replace("ORGANIZER:mailto:me@gmail.com", "")


def test_delete_finds_event_then_deletes(rec, capsys):
    rec.responses = [("GET", ".ics", (200, EXISTING_ICS))]
    out = _run(["calendar", "delete", "--id", "evt-timed@google.com"], capsys)
    delete = next(c for c in rec.calls if c["method"] == "DELETE")
    assert delete["url"].endswith("/events/evt-timed%40google.com.ics")
    assert '"deleted"' in out


def test_respond_sets_partstat_for_self(rec, capsys):
    rec.responses = [("GET", ".ics", (200, EXISTING_ICS))]
    out = _run(["calendar", "respond", "--id", "evt-timed@google.com", "--response", "accept"], capsys)
    put = next(c for c in rec.calls if c["method"] == "PUT")
    assert "ATTENDEE;PARTSTAT=ACCEPTED:mailto:me@gmail.com" in put["body"]
    assert '"accepted"' in out


def test_respond_when_not_an_attendee_errors(rec, monkeypatch, capsys):
    monkeypatch.setattr(caldav_client, "caldav_account", lambda account: _ctx(user="other@gmail.com"))
    rec.responses = [("GET", ".ics", (200, EXISTING_ICS))]
    with pytest.raises(SystemExit) as ei:
        _run(["calendar", "respond", "--id", "evt-timed@google.com", "--response", "accept"], capsys)
    assert "not an attendee" in str(ei.value)


# -- redirects (iCloud partition hosts) -----------------------------------


class _FakeResponse(io.BytesIO):
    status = 207


def test_request_follows_redirect_with_method_and_auth(monkeypatch):
    monkeypatch.setattr(caldav_client, "_auth_header", lambda ctx: "Basic abc")
    seen = []

    def fake_urlopen(req, timeout=0):
        seen.append({"url": req.full_url, "method": req.get_method(), "auth": req.get_header("Authorization")})
        if len(seen) == 1:
            raise urllib.error.HTTPError(
                req.full_url, 301, "moved", {"Location": "https://p42-caldav.icloud.com/12345/principal/"}, io.BytesIO(b"")
            )
        return _FakeResponse(b"<D:multistatus xmlns:D='DAV:'/>")

    monkeypatch.setattr(caldav_client.urllib.request, "urlopen", fake_urlopen)
    ctx = _ctx(auth="basic", base_url="https://caldav.icloud.com")
    status, _, final = caldav_client.request(ctx, "PROPFIND", "https://caldav.icloud.com/", body="<x/>", depth="0")
    assert status == 207
    assert final == "https://p42-caldav.icloud.com/12345/principal/"
    assert [s["method"] for s in seen] == ["PROPFIND", "PROPFIND"]
    assert all(s["auth"] == "Basic abc" for s in seen)


# -- recurrence expansion (ics) -------------------------------------------


def _vcal(*event_lines: str) -> ics.Component:
    text = "BEGIN:VCALENDAR\nVERSION:2.0\n" + "\n".join(event_lines) + "\nEND:VCALENDAR\n"
    return ics.parse_calendar(text)


def _starts(vcal, start, end):
    return [occ.start for occ in ics.expand(vcal, start, end)]


WINDOW_START = dt.datetime(2026, 7, 1, tzinfo=dt.UTC)
WINDOW_END = dt.datetime(2026, 9, 1, tzinfo=dt.UTC)


def test_expand_weekly_byday(monkeypatch):
    vcal = _vcal(
        "BEGIN:VEVENT",
        "UID:w1",
        "DTSTART;TZID=Europe/Rome:20260706T100000",
        "DTEND;TZID=Europe/Rome:20260706T110000",
        "RRULE:FREQ=WEEKLY;WKST=SU;BYDAY=MO,WE",
        "END:VEVENT",
    )
    starts = _starts(vcal, WINDOW_START, dt.datetime(2026, 7, 20, tzinfo=dt.UTC))
    # Mon 6, Wed 8, Mon 13, Wed 15 July (Mon 20 is outside the window).
    assert [s.date().isoformat() for s in starts] == ["2026-07-06", "2026-07-08", "2026-07-13", "2026-07-15"]
    assert all(s.hour == 10 for s in starts)


def test_expand_until_date_is_inclusive():
    vcal = _vcal(
        "BEGIN:VEVENT",
        "UID:u1",
        "DTSTART:20260701T120000Z",
        "DTEND:20260701T130000Z",
        "RRULE:FREQ=DAILY;UNTIL=20260703",
        "END:VEVENT",
    )
    starts = _starts(vcal, WINDOW_START, WINDOW_END)
    assert [s.date().isoformat() for s in starts] == ["2026-07-01", "2026-07-02", "2026-07-03"]


def test_expand_exdate_removes_occurrence():
    vcal = _vcal(
        "BEGIN:VEVENT",
        "UID:e1",
        "DTSTART:20260701T120000Z",
        "DTEND:20260701T130000Z",
        "RRULE:FREQ=DAILY;COUNT=3",
        "EXDATE:20260702T120000Z",
        "END:VEVENT",
    )
    starts = _starts(vcal, WINDOW_START, WINDOW_END)
    assert [s.date().isoformat() for s in starts] == ["2026-07-01", "2026-07-03"]


def test_expand_recurrence_id_override_replaces_occurrence():
    vcal = _vcal(
        "BEGIN:VEVENT",
        "UID:o1",
        "DTSTART:20260701T120000Z",
        "DTEND:20260701T130000Z",
        "SUMMARY:Series",
        "RRULE:FREQ=DAILY;COUNT=2",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:o1",
        "RECURRENCE-ID:20260702T120000Z",
        "DTSTART:20260702T150000Z",
        "DTEND:20260702T160000Z",
        "SUMMARY:Moved",
        "END:VEVENT",
    )
    occurrences = ics.expand(vcal, WINDOW_START, WINDOW_END)
    assert len(occurrences) == 2
    moved = occurrences[1]
    assert ics.first_prop(moved.vevent, "SUMMARY").value == "Moved"
    assert moved.start == dt.datetime(2026, 7, 2, 15, 0, tzinfo=dt.UTC)


def test_expand_monthly_ordinal_byday():
    vcal = _vcal(
        "BEGIN:VEVENT",
        "UID:m1",
        "DTSTART:20260714T090000Z",  # second Tuesday of July 2026
        "DTEND:20260714T100000Z",
        "RRULE:FREQ=MONTHLY;BYDAY=2TU;COUNT=2",
        "END:VEVENT",
    )
    starts = _starts(vcal, WINDOW_START, WINDOW_END)
    assert [s.date().isoformat() for s in starts] == ["2026-07-14", "2026-08-11"]


def test_expand_all_day_weekly():
    vcal = _vcal(
        "BEGIN:VEVENT",
        "UID:a1",
        "DTSTART;VALUE=DATE:20260703",
        "DTEND;VALUE=DATE:20260704",
        "RRULE:FREQ=WEEKLY;COUNT=3",
        "END:VEVENT",
    )
    starts = _starts(vcal, WINDOW_START, WINDOW_END)
    assert starts == [dt.date(2026, 7, 3), dt.date(2026, 7, 10), dt.date(2026, 7, 17)]


def test_expand_unsupported_rule_falls_back_to_master_only():
    vcal = _vcal(
        "BEGIN:VEVENT",
        "UID:x1",
        "DTSTART:20260701T120000Z",
        "DTEND:20260701T130000Z",
        "RRULE:FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
        "END:VEVENT",
    )
    starts = _starts(vcal, WINDOW_START, WINDOW_END)
    assert starts == [dt.datetime(2026, 7, 1, 12, 0, tzinfo=dt.UTC)]


def test_serialize_round_trips_unknown_props_and_folds_long_lines():
    vcal = _vcal(
        "BEGIN:VEVENT",
        "UID:r1",
        "DTSTART:20260701T120000Z",
        'X-CUSTOM;PARAM="a,b":' + "y" * 200,
        "END:VEVENT",
    )
    vevent = ics.vevents(vcal)[0]
    ics.set_prop(vevent, "SUMMARY", ics.escape_text("hi\nthere"))
    text = ics.serialize(vcal)
    assert "SUMMARY:hi\\nthere" in text
    assert all(len(line) <= 75 for line in text.split("\r\n"))
    reparsed = ics.parse_calendar(text)
    custom = ics.first_prop(ics.vevents(reparsed)[0], "X-CUSTOM")
    assert custom.value == "y" * 200
    assert custom.params["PARAM"] == '"a,b"'
