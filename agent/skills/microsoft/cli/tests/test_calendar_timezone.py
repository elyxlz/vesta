"""Timezone reporting for calendar reads.

The OWA REST calendar endpoints always answer in UTC, so `--user-timezone` is applied on
read; the Graph path pushes the same request upstream through a Prefer header. Both
backends resolve the default zone and reject an invalid one through `resolve_timezone`.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from microsoft_cli import calendar, owa_rest, owa_rest_commands

ACCOUNT = "user@example.com"


class _FakeConfig:
    """Minimal config stand-in with a data_dir."""

    def __init__(self, tmp_path: Path) -> None:
        self.data_dir = tmp_path


def _cfg(tmp_path: Path) -> _FakeConfig:
    cfg = _FakeConfig(tmp_path)
    owa_rest.save_token(ACCOUNT, cfg, token="test-tok", expires_at=time.time() + 7200)
    return cfg


def _client(json_response: dict) -> httpx.Client:
    """Return a mock httpx.Client whose get() returns the given JSON."""
    mock = MagicMock(spec=httpx.Client)
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = json_response
    resp.raise_for_status = MagicMock()
    mock.get.return_value = resp
    return mock


def _stored_event(start: str, end: str, *, all_day: bool = False) -> dict:
    """An event as the OWA REST endpoint returns it: Pascal-cased, always in UTC."""
    return {
        "Id": "e1",
        "Subject": "Standup",
        "IsAllDay": all_day,
        "Start": {"DateTime": start, "TimeZone": "UTC"},
        "End": {"DateTime": end, "TimeZone": "UTC"},
    }


def test_owa_rest_list_events_reports_a_utc_event_in_the_requested_timezone(tmp_path):
    client = _client({"value": [_stored_event("2026-08-15T12:00:00Z", "2026-08-15T13:00:00Z")]})
    events = owa_rest_commands.list_events(_cfg(tmp_path), client, account_email=ACCOUNT, user_timezone="Europe/Rome")
    assert events[0]["start"] == {"dateTime": "2026-08-15T14:00:00", "timeZone": "Europe/Rome"}
    assert events[0]["end"] == {"dateTime": "2026-08-15T15:00:00", "timeZone": "Europe/Rome"}


@pytest.mark.parametrize(
    ("timezone", "expected"),
    [
        ("UTC", "2026-08-15T12:00:00"),
        ("Europe/Rome", "2026-08-15T14:00:00"),
        ("Asia/Tokyo", "2026-08-15T21:00:00"),
        ("America/Los_Angeles", "2026-08-15T05:00:00"),
    ],
)
def test_owa_rest_list_events_start_tracks_the_requested_timezone(tmp_path, timezone, expected):
    client = _client({"value": [_stored_event("2026-08-15T12:00:00Z", "2026-08-15T13:00:00Z")]})
    events = owa_rest_commands.list_events(_cfg(tmp_path), client, account_email=ACCOUNT, user_timezone=timezone)
    assert events[0]["start"] == {"dateTime": expected, "timeZone": timezone}


def test_owa_rest_list_events_defaults_to_the_local_timezone(tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    client = _client({"value": [_stored_event("2026-08-15T12:00:00Z", "2026-08-15T13:00:00Z")]})
    events = owa_rest_commands.list_events(_cfg(tmp_path), client, account_email=ACCOUNT)
    assert events[0]["start"] == {"dateTime": "2026-08-15T21:00:00", "timeZone": "Asia/Tokyo"}


def test_owa_rest_list_events_keeps_all_day_events_on_their_own_date(tmp_path):
    client = _client({"value": [_stored_event("2026-08-15T00:00:00Z", "2026-08-16T00:00:00Z", all_day=True)]})
    events = owa_rest_commands.list_events(_cfg(tmp_path), client, account_email=ACCOUNT, user_timezone="America/Los_Angeles")
    assert events[0]["start"] == {"dateTime": "2026-08-15T00:00:00", "timeZone": "America/Los_Angeles"}
    assert events[0]["end"] == {"dateTime": "2026-08-16T00:00:00", "timeZone": "America/Los_Angeles"}


def test_owa_rest_list_events_preserves_the_other_event_fields(tmp_path):
    client = _client({"value": [_stored_event("2026-08-15T12:00:00Z", "2026-08-15T13:00:00Z")]})
    events = owa_rest_commands.list_events(_cfg(tmp_path), client, account_email=ACCOUNT, user_timezone="Europe/Rome")
    assert events[0]["id"] == "e1"
    assert events[0]["subject"] == "Standup"


def test_owa_rest_get_event_reports_times_in_the_requested_timezone(tmp_path):
    client = _client(_stored_event("2026-08-15T12:00:00Z", "2026-08-15T13:00:00Z"))
    event = owa_rest_commands.get_event(_cfg(tmp_path), client, account_email=ACCOUNT, event_id="e1", user_timezone="Europe/Rome")
    assert event["start"] == {"dateTime": "2026-08-15T14:00:00", "timeZone": "Europe/Rome"}
    assert event["end"] == {"dateTime": "2026-08-15T15:00:00", "timeZone": "Europe/Rome"}


def test_owa_rest_list_events_rejects_an_unknown_timezone(tmp_path):
    client = _client({"value": []})
    with pytest.raises(ValueError, match="Invalid timezone"):
        owa_rest_commands.list_events(_cfg(tmp_path), client, account_email=ACCOUNT, user_timezone="Mars/Olympus")


def test_resolve_timezone_rejects_an_unknown_timezone():
    with pytest.raises(ValueError, match="Invalid timezone"):
        calendar.resolve_timezone("Mars/Olympus")


def test_resolve_timezone_defaults_to_the_local_timezone(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Rome")
    assert calendar.resolve_timezone(None) == "Europe/Rome"
