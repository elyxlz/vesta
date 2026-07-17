"""Unit tests for microsoft_cli.monitor preview / timestamp helpers and OWA REST polling."""

import logging
import types
from datetime import UTC, datetime

from microsoft_cli import monitor
from microsoft_cli.monitor import clean_preview, strip_fractional


def test_clean_preview_strips_zero_width_and_bidi():
    # Real-world pattern: Booking.com-style invisible padding between words.
    raw = "Go further for less\r\n ‌​‍‎‏﻿ ‌​ hey"
    assert clean_preview(raw) == "Go further for less hey"


def test_clean_preview_collapses_whitespace():
    assert clean_preview("a\n\n  b\t\tc") == "a b c"


def test_clean_preview_handles_empty():
    assert clean_preview("") == ""


def test_strip_fractional_removes_graph_start_time_padding():
    # Graph returns '2026-05-01T07:00:00.0000000' — seven trailing zeros.
    assert strip_fractional("2026-05-01T07:00:00.0000000") == "2026-05-01T07:00:00"


def test_strip_fractional_preserves_timezone_suffix():
    assert strip_fractional("2026-05-01T07:00:00.123Z") == "2026-05-01T07:00:00Z"
    assert strip_fractional("2026-05-01T07:00:00.123+00:00") == "2026-05-01T07:00:00+00:00"


def test_strip_fractional_leaves_non_fractional_intact():
    assert strip_fractional("2026-05-01T07:00:00") == "2026-05-01T07:00:00"


# ---------------------------------------------------------------------------
# OWA REST polling: locked-tenant accounts get mail + calendar notifications,
# and the fetch keeps their token warm (auto-refresh runs through load_token)
# ---------------------------------------------------------------------------


def _fake_ctx(tmp_path):
    return types.SimpleNamespace(
        monitor_logger=logging.getLogger("test-monitor"),
        notif_dir=tmp_path,
        http_client=None,
        cache_file=tmp_path / "auth_cache.bin",
        get_calendar_notify_thresholds=lambda: [10080, 60, 15],
    )


def _email(addr, name, received):
    return {
        "id": "m1",
        "from": {"emailAddress": {"address": addr, "name": name}},
        "subject": "hello",
        "bodyPreview": "preview",
        "receivedDateTime": received,
    }


def test_emit_email_notification_writes_with_sender(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(monitor.notifications, "write_notification", lambda *a, **k: calls.append(k))
    monitor._emit_email_notification(_fake_ctx(tmp_path), _email("a@b.com", "Alice", "2026-07-08T13:00:00Z"), "me@x.com", "inbox", False)
    assert len(calls) == 1
    assert calls[0]["sender"] == "Alice"
    assert calls[0]["account"] == "me@x.com"


def test_poll_owa_rest_notifies_only_new_mail(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(monitor.notifications, "write_notification", lambda *a, **k: calls.append(k))
    monkeypatch.setattr(
        monitor.owa_rest,
        "list_messages",
        lambda *a, **k: [
            _email("new@x.com", "New Sender", "2026-07-08T13:00:00Z"),
            _email("old@x.com", "Old Sender", "2026-07-08T11:00:00Z"),
        ],
    )
    monkeypatch.setattr(monitor.owa_rest, "list_events", lambda *a, **k: [])
    last_dt = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    new_check = datetime(2026, 7, 8, 13, 30, tzinfo=UTC)
    monitor._poll_owa_rest_account(_fake_ctx(tmp_path), None, "me@x.com", ["inbox"], last_dt, new_check, False)
    assert len(calls) == 1
    assert calls[0]["sender"] == "New Sender"


def test_poll_owa_rest_fires_calendar_reminder(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(monitor.notifications, "write_notification", lambda *a, **k: calls.append(k))
    monkeypatch.setattr(monitor.owa_rest, "list_messages", lambda *a, **k: [])
    monkeypatch.setattr(
        monitor.owa_rest,
        "list_events",
        lambda *a, **k: [
            {"id": "e1", "subject": "Standup", "start": {"dateTime": "2026-07-08T13:00:00Z"}, "location": {"displayName": "Room 1"}}
        ],
    )
    # the 60-minute reminder (trigger 12:00) falls in this cycle's window
    last_dt = datetime(2026, 7, 8, 11, 59, tzinfo=UTC)
    new_check = datetime(2026, 7, 8, 12, 0, 30, tzinfo=UTC)
    monitor._poll_owa_rest_account(_fake_ctx(tmp_path), None, "me@x.com", ["inbox"], last_dt, new_check, False)
    assert len(calls) == 1
    assert calls[0]["subject"] == "Standup"
