"""Calendar command routing + Google Calendar REST v3 request construction.

calendar_client imports imap_client (which needs imap_tools from the on-box
runtime). We stub imap_tools so the module imports without the venv, then
mock the single HTTP choke point (``calendar_client._http``) and the account
plumbing to assert the exact endpoints, query params, and JSON bodies the
commands build, plus that non-Google accounts (and pre-calendar tokens) are
rejected.
"""

import argparse
import sys
import types
import pathlib

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
import calendar_client  # noqa: E402


# -- harness -------------------------------------------------------


def _parse(argv):
    """Route argv through the real parser tree, exactly as email-client does."""
    ap = argparse.ArgumentParser(prog="email-client")
    sub = ap.add_subparsers(dest="cmd", required=True)
    calendar_client.build_parser(sub)
    return ap.parse_args(argv)


class _Recorder:
    """Capture calendar_client._http calls and feed canned responses."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, method, url, token, body=None):
        self.calls.append({"method": method, "url": url, "token": token, "body": body})
        # Match a canned response by (method, substring) if provided.
        for (m, needle), resp in self.responses.items():
            if m == method and needle in url:
                return resp
        return {}


@pytest.fixture
def rec(monkeypatch):
    """Bypass account plumbing; record HTTP calls."""
    monkeypatch.setattr(calendar_client, "google_account_token", lambda acct: ("personal", "TOKEN"))
    r = _Recorder()
    monkeypatch.setattr(calendar_client, "_http", r)
    return r


def _run(argv, capsys):
    args = _parse(argv)
    calendar_client.dispatch(args)
    return capsys.readouterr().out


# -- routing + request construction --------------------------------


def test_list_calendars_endpoint(rec, capsys):
    rec.responses = {("GET", "calendarList"): {"items": [{"id": "primary", "summary": "Me", "primary": True}]}}
    out = _run(["calendar", "list-calendars", "--account", "personal"], capsys)
    assert len(rec.calls) == 1
    c = rec.calls[0]
    assert c["method"] == "GET"
    assert c["url"] == "https://www.googleapis.com/calendar/v3/users/me/calendarList"
    assert c["token"] == "TOKEN"
    assert "primary" in out


def test_list_events_endpoint_and_params(rec, capsys):
    rec.responses = {("GET", "/events"): {"items": []}}
    _run(["calendar", "list", "--days-ahead", "3", "--days-back", "1"], capsys)
    c = rec.calls[0]
    assert c["method"] == "GET"
    assert c["url"].startswith("https://www.googleapis.com/calendar/v3/calendars/primary/events?")
    assert "singleEvents=true" in c["url"]
    assert "orderBy=startTime" in c["url"]
    assert "maxResults=250" in c["url"]
    assert "timeMin=" in c["url"] and "timeMax=" in c["url"]


def test_list_events_custom_calendar_is_url_encoded(rec, capsys):
    rec.responses = {("GET", "/events"): {"items": []}}
    _run(["calendar", "list", "--calendar", "team@group.calendar.google.com"], capsys)
    c = rec.calls[0]
    assert "/calendars/team%40group.calendar.google.com/events" in c["url"]


def test_get_event_endpoint(rec, capsys):
    _run(["calendar", "get", "--id", "evt123"], capsys)
    c = rec.calls[0]
    assert c["method"] == "GET"
    assert c["url"] == "https://www.googleapis.com/calendar/v3/calendars/primary/events/evt123"


def test_create_event_body_and_send_updates(rec, capsys):
    rec.responses = {("POST", "/events"): {"id": "new1"}}
    _run(
        [
            "calendar",
            "create",
            "--subject",
            "Sync",
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
    c = rec.calls[0]
    assert c["method"] == "POST"
    assert c["url"].startswith("https://www.googleapis.com/calendar/v3/calendars/primary/events?")
    assert "sendUpdates=all" in c["url"]
    body = c["body"]
    assert body["summary"] == "Sync"
    assert body["start"] == {"dateTime": "2026-07-20T15:00:00", "timeZone": "Europe/London"}
    assert body["end"] == {"dateTime": "2026-07-20T16:00:00", "timeZone": "Europe/London"}
    assert body["location"] == "Room 1"
    assert [a["email"] for a in body["attendees"]] == ["a@x.com", "b@y.com", "c@z.com"]


def test_create_event_defaults_end_to_plus_one_hour(rec, capsys):
    _run(["calendar", "create", "--subject", "Quick", "--start", "2026-07-20T09:00:00"], capsys)
    body = rec.calls[0]["body"]
    assert body["end"]["dateTime"] == "2026-07-20T10:00:00"
    assert body["start"]["timeZone"] == "UTC"  # default timezone


def test_create_all_day_event_uses_exclusive_end_date(rec, capsys):
    _run(["calendar", "create", "--subject", "Holiday", "--start", "2026-12-25"], capsys)
    body = rec.calls[0]["body"]
    assert body["start"] == {"date": "2026-12-25"}
    # all-day end date is exclusive => next day
    assert body["end"] == {"date": "2026-12-26"}


def test_update_event_patch_and_send_updates(rec, capsys):
    rec.responses = {("PATCH", "/events"): {"id": "evt1"}}
    _run(["calendar", "update", "--id", "evt1", "--subject", "Renamed"], capsys)
    c = rec.calls[0]
    assert c["method"] == "PATCH"
    assert c["url"].startswith("https://www.googleapis.com/calendar/v3/calendars/primary/events/evt1?")
    assert "sendUpdates=all" in c["url"]
    assert c["body"] == {"summary": "Renamed"}


def test_update_start_requires_timezone(rec, capsys):
    with pytest.raises(SystemExit) as ei:
        _run(["calendar", "update", "--id", "evt1", "--start", "2026-07-20T10:00:00"], capsys)
    assert "timezone" in str(ei.value).lower()


def test_update_with_no_fields_errors(rec, capsys):
    with pytest.raises(SystemExit) as ei:
        _run(["calendar", "update", "--id", "evt1"], capsys)
    assert "nothing to update" in str(ei.value).lower()


def test_delete_event_endpoint(rec, capsys):
    out = _run(["calendar", "delete", "--id", "evt9"], capsys)
    c = rec.calls[0]
    assert c["method"] == "DELETE"
    assert c["url"].startswith("https://www.googleapis.com/calendar/v3/calendars/primary/events/evt9?")
    assert "sendUpdates=all" in c["url"]
    assert '"deleted"' in out


def test_respond_sets_self_attendee_status(monkeypatch, capsys):
    monkeypatch.setattr(calendar_client, "google_account_token", lambda acct: ("personal", "TOKEN"))
    monkeypatch.setattr(calendar_client.imap_client, "account_user", lambda acc: "me@gmail.com")
    rec = _Recorder(
        responses={
            ("GET", "/events/evt5"): {
                "id": "evt5",
                "attendees": [
                    {"email": "other@x.com", "responseStatus": "needsAction"},
                    {"email": "me@gmail.com", "self": True, "responseStatus": "needsAction"},
                ],
            }
        }
    )
    monkeypatch.setattr(calendar_client, "_http", rec)
    out = _run(["calendar", "respond", "--id", "evt5", "--response", "accept"], capsys)

    assert rec.calls[0]["method"] == "GET"
    patch = rec.calls[1]
    assert patch["method"] == "PATCH"
    assert "sendUpdates=all" in patch["url"]
    me = [a for a in patch["body"]["attendees"] if a.get("self")][0]
    assert me["responseStatus"] == "accepted"
    assert '"accepted"' in out


# -- gating: non-Google accounts and stale tokens ------------------


def _fake_profile(monkeypatch, strategy, token=None):
    monkeypatch.setattr(calendar_client.imap_client, "resolve_account", lambda a: "acct")
    monkeypatch.setattr(calendar_client.imap_client, "account_profile", lambda a: ("prov", {"auth_strategy": strategy}))
    monkeypatch.setattr(calendar_client.imap_client, "load_token", lambda a: token)
    monkeypatch.setattr(calendar_client.imap_client, "get_access_token", lambda a: "TOKEN")


def test_non_google_account_rejected(monkeypatch):
    _fake_profile(monkeypatch, "device-flow", token={"access_token": "x"})
    with pytest.raises(SystemExit) as ei:
        calendar_client.google_account_token("acct")
    assert "only supported for Google" in str(ei.value)


def test_app_password_account_rejected(monkeypatch):
    _fake_profile(monkeypatch, "app-password", token={"app_password": "x"})
    with pytest.raises(SystemExit) as ei:
        calendar_client.google_account_token("acct")
    assert "only supported for Google" in str(ei.value)


def test_google_account_without_calendar_scope_tells_user_to_reauth(monkeypatch):
    _fake_profile(monkeypatch, "loopback-oauth", token={"scope": "https://mail.google.com/"})
    with pytest.raises(SystemExit) as ei:
        calendar_client.google_account_token("acct")
    msg = str(ei.value)
    assert "reauth" in msg.lower() or "--reauth" in msg


def test_google_account_with_calendar_scope_passes(monkeypatch):
    _fake_profile(
        monkeypatch,
        "loopback-oauth",
        token={"scope": "https://mail.google.com/ https://www.googleapis.com/auth/calendar"},
    )
    acc, token = calendar_client.google_account_token("acct")
    assert acc == "acct"
    assert token == "TOKEN"


def test_google_account_without_scope_field_is_not_blocked(monkeypatch):
    # Older/unknown token shape (no 'scope' key): don't pre-block; let the API decide.
    _fake_profile(monkeypatch, "loopback-oauth", token={"access_token": "x"})
    acc, token = calendar_client.google_account_token("acct")
    assert (acc, token) == ("acct", "TOKEN")
