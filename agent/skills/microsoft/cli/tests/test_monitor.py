"""Unit tests for microsoft_cli.monitor preview / timestamp helpers and OWA REST polling."""

import json
import logging
import types
from datetime import UTC, datetime, timedelta

import httpx
from microsoft_cli import monitor
from microsoft_cli.monitor import clean_preview, strip_fractional


def _raise(exc: Exception):
    def fail(*_args, **_kwargs):
        raise exc

    return fail


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


def _mailbox(*emails):
    """A fake OWA REST fetch honoring the real one's contract: newer than since_utc, oldest first,
    capped at limit."""

    def fetch(_client, _account, _config, *, folder, since_utc, limit):
        since = datetime.fromisoformat(since_utc)
        window = [email for email in emails if datetime.fromisoformat(email["receivedDateTime"]) > since]
        return sorted(window, key=lambda email: datetime.fromisoformat(email["receivedDateTime"]))[:limit]

    return fetch


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
        "list_messages_since",
        _mailbox(
            _email("new@x.com", "New Sender", "2026-07-08T13:00:00+00:00"),
            _email("old@x.com", "Old Sender", "2026-07-08T11:00:00+00:00"),
        ),
    )
    last_dt = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    new_check = datetime(2026, 7, 8, 14, 0, tzinfo=UTC)
    assert monitor._poll_owa_rest_mail(_fake_ctx(tmp_path), None, "me@x.com", ["inbox"], new_check, last_dt, False) == new_check
    assert len(calls) == 1
    assert calls[0]["sender"] == "New Sender"


def test_poll_owa_rest_mail_reports_a_folder_it_could_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor.owa_rest, "list_messages_since", _raise(httpx.ConnectError("boom")))
    last_dt = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    new_check = datetime(2026, 7, 8, 14, 0, tzinfo=UTC)
    assert monitor._poll_owa_rest_mail(_fake_ctx(tmp_path), None, "me@x.com", ["inbox"], new_check, last_dt, False) is None


def test_poll_owa_rest_fires_calendar_reminder(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(monitor.notifications, "write_notification", lambda *a, **k: calls.append(k))
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
    assert monitor._poll_owa_rest_calendar(_fake_ctx(tmp_path), None, "me@x.com", new_check, last_dt, False) is True
    assert len(calls) == 1
    assert calls[0]["subject"] == "Standup"


def test_poll_owa_rest_calendar_reports_a_calendar_it_could_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor.owa_rest, "list_events", _raise(httpx.ConnectError("boom")))
    last_dt = datetime(2026, 7, 8, 11, 59, tzinfo=UTC)
    new_check = datetime(2026, 7, 8, 12, 0, 30, tzinfo=UTC)
    assert monitor._poll_owa_rest_calendar(_fake_ctx(tmp_path), None, "me@x.com", new_check, last_dt, False) is False


def _run_ctx(tmp_path, cycles: int):
    """A context whose stop event ends run() after `cycles` iterations."""
    remaining = {"cycles": cycles}

    def wait(_timeout):
        remaining["cycles"] -= 1
        return remaining["cycles"] <= 0

    ctx = _fake_ctx(tmp_path)
    ctx.monitor_state_file = tmp_path / "state.txt"
    ctx.monitor_stop_event = types.SimpleNamespace(is_set=lambda: False, wait=wait)
    ctx.notify_file = None
    ctx.scopes = []
    ctx.base_url = "https://graph.invalid/v1.0"
    ctx.folders = {"inbox": "inbox"}
    return ctx


def _single_owa_account(monkeypatch, account: str = "me@x.com"):
    """Only one OWA REST account exists: no MSAL, no Teams, no token refresh."""
    monkeypatch.setattr(monitor.auth, "list_accounts", lambda *a, **k: [])
    monkeypatch.setattr(monitor.teams, "list_accounts", lambda *a, **k: [])
    monkeypatch.setattr(monitor.capture, "due_accounts", lambda *a, **k: [])
    monkeypatch.setattr(monitor.owa_rest, "list_accounts", lambda *a, **k: [account])
    monkeypatch.setattr(monitor.owa_rest, "list_events", lambda *a, **k: [])


def _watermark(ctx, unit: str) -> datetime:
    return datetime.fromisoformat(json.loads(ctx.monitor_state_file.read_text())["units"][unit])


def test_failed_poll_leaves_the_window_for_the_next_cycle_to_recover(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(monitor.notifications, "write_notification", lambda *a, **k: calls.append(k))
    _single_owa_account(monkeypatch)

    now = datetime.now(UTC)
    ctx = _run_ctx(tmp_path, cycles=2)
    ctx.monitor_state_file.write_text((now - timedelta(seconds=60)).isoformat())
    arrived_at = now - timedelta(seconds=30)
    arrived = _email("boss@x.com", "Manager", arrived_at.isoformat())

    cycle = {"n": 0}

    def list_messages_since(*_args, **_kwargs):
        cycle["n"] += 1
        if cycle["n"] == 1:
            raise httpx.ConnectError("Server disconnected without sending a response.")
        return [arrived]

    monkeypatch.setattr(monitor.owa_rest, "list_messages_since", list_messages_since)
    monitor.run(ctx)

    assert [call["sender"] for call in calls] == ["Manager"]
    assert _watermark(ctx, "mail:me@x.com") > arrived_at


def test_broken_account_does_not_make_a_healthy_one_renotify(tmp_path, monkeypatch):
    """Guards the per-account granularity: one global watermark would re-notify every healthy
    account's window each cycle until the broken one heals."""
    calls = []
    monkeypatch.setattr(monitor.notifications, "write_notification", lambda *a, **k: calls.append(k))
    _single_owa_account(monkeypatch)
    monkeypatch.setattr(monitor.owa_rest, "list_accounts", lambda *a, **k: ["broken@x.com", "healthy@x.com"])

    now = datetime.now(UTC)
    parked_at = now - timedelta(seconds=60)
    delivered_at = now - timedelta(seconds=30)
    ctx = _run_ctx(tmp_path, cycles=2)
    ctx.monitor_state_file.write_text(parked_at.isoformat())
    delivered = _email("colleague@x.com", "Colleague", delivered_at.isoformat())

    healthy = _mailbox(delivered)

    def list_messages_since(client, account_email, config, **kwargs):
        if account_email == "broken@x.com":
            raise httpx.ConnectError("token is dead")
        return healthy(client, account_email, config, **kwargs)

    monkeypatch.setattr(monitor.owa_rest, "list_messages_since", list_messages_since)
    monitor.run(ctx)

    assert [call["sender"] for call in calls] == ["Colleague"]
    assert _watermark(ctx, "mail:broken@x.com") == parked_at
    assert _watermark(ctx, "mail:healthy@x.com") > delivered_at


def test_recovery_reads_at_most_the_max_catchup_window(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(monitor.notifications, "write_notification", lambda *a, **k: calls.append(k))
    _single_owa_account(monkeypatch)

    now = datetime.now(UTC)
    ctx = _run_ctx(tmp_path, cycles=1)
    stale = {"last_cycle": now.isoformat(), "units": {"mail:me@x.com": (now - timedelta(days=30)).isoformat()}}
    ctx.monitor_state_file.write_text(json.dumps(stale))
    monkeypatch.setattr(
        monitor.owa_rest,
        "list_messages_since",
        _mailbox(
            _email("ancient@x.com", "Ancient", (now - timedelta(days=20)).isoformat()),
            _email("recent@x.com", "Recent", (now - timedelta(hours=1)).isoformat()),
        ),
    )
    monitor.run(ctx)

    assert [call["sender"] for call in calls] == ["Recent"]
    assert calls[0]["missed"] is True


def test_legacy_bare_timestamp_state_is_read_as_the_starting_watermark(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(monitor.notifications, "write_notification", lambda *a, **k: calls.append(k))
    _single_owa_account(monkeypatch)

    now = datetime.now(UTC)
    ctx = _run_ctx(tmp_path, cycles=1)
    ctx.monitor_state_file.write_text((now - timedelta(minutes=5)).isoformat())
    monkeypatch.setattr(
        monitor.owa_rest,
        "list_messages_since",
        _mailbox(
            _email("before@x.com", "Before", (now - timedelta(minutes=10)).isoformat()),
            _email("after@x.com", "After", (now - timedelta(minutes=2)).isoformat()),
        ),
    )
    monitor.run(ctx)

    assert [call["sender"] for call in calls] == ["After"]


def _oversized_window(now: datetime, count: int) -> list[dict]:
    """`count` emails arriving one second apart, oldest first, all inside the last cycle's window."""
    return [_email(f"s{i}@x.com", f"S{i}", (now - timedelta(seconds=count - i)).isoformat()) for i in range(count)]


def test_a_window_over_the_drain_limit_parks_the_watermark_at_the_last_message_read(tmp_path, monkeypatch):
    """The cap and the watermark are one decision: a full-limit fetch cannot advance past mail it never fetched."""
    calls = []
    monkeypatch.setattr(monitor.notifications, "write_notification", lambda *a, **k: calls.append(k))
    _single_owa_account(monkeypatch)

    now = datetime.now(UTC)
    over_limit = monitor._MAX_WINDOW_MESSAGES + 100
    mailbox = _oversized_window(now, over_limit)
    ctx = _run_ctx(tmp_path, cycles=1)
    ctx.monitor_state_file.write_text((now - timedelta(seconds=over_limit + 1)).isoformat())
    monkeypatch.setattr(monitor.owa_rest, "list_messages_since", _mailbox(*mailbox))
    monitor.run(ctx)

    drained = mailbox[: monitor._MAX_WINDOW_MESSAGES]
    assert [call["sender"] for call in calls] == [call["from"]["emailAddress"]["name"] for call in drained]
    # Parked one second before the last message read, so the boundary second is re-scanned next cycle.
    assert _watermark(ctx, "mail:me@x.com") == datetime.fromisoformat(drained[-1]["receivedDateTime"]) - timedelta(seconds=1)
    assert _watermark(ctx, "mail:me@x.com") < datetime.fromisoformat(mailbox[monitor._MAX_WINDOW_MESSAGES]["receivedDateTime"])


def test_the_rest_of_an_oversized_window_is_drained_by_the_following_cycle(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(monitor.notifications, "write_notification", lambda *a, **k: calls.append(k))
    _single_owa_account(monkeypatch)

    now = datetime.now(UTC)
    over_limit = monitor._MAX_WINDOW_MESSAGES + 100
    mailbox = _oversized_window(now, over_limit)
    ctx = _run_ctx(tmp_path, cycles=2)
    ctx.monitor_state_file.write_text((now - timedelta(seconds=over_limit + 1)).isoformat())
    monkeypatch.setattr(monitor.owa_rest, "list_messages_since", _mailbox(*mailbox))
    monitor.run(ctx)

    delivered = [call["sender"] for call in calls]
    boundary = mailbox[monitor._MAX_WINDOW_MESSAGES - 1]["from"]["emailAddress"]["name"]
    # Every message is delivered; the truncation boundary's second is re-scanned, so it repeats once.
    assert set(delivered) == {email["from"]["emailAddress"]["name"] for email in mailbox}
    assert delivered.count(boundary) == 2


def test_a_boundary_second_tie_in_a_truncated_window_is_not_dropped(tmp_path, monkeypatch):
    """A 501st message sharing the 500th's second is split out of the truncated window. Strict `gt` at
    the 500th's timestamp would drop it forever; parking one second early re-scans the tie into the next
    cycle. Discriminates against the old park-at-newest behavior, under which "Tie" never arrives."""
    calls = []
    monkeypatch.setattr(monitor.notifications, "write_notification", lambda *a, **k: calls.append(k))
    _single_owa_account(monkeypatch)

    now = datetime.now(UTC)
    limit = monitor._MAX_WINDOW_MESSAGES
    window = _oversized_window(now, limit)  # `limit` messages, one second apart, oldest first
    tied = _email("tie@x.com", "Tie", window[-1]["receivedDateTime"])  # shares the 500th's second
    mailbox = [*window, tied]

    ctx = _run_ctx(tmp_path, cycles=2)
    ctx.monitor_state_file.write_text((now - timedelta(seconds=limit + 1)).isoformat())
    monkeypatch.setattr(monitor.owa_rest, "list_messages_since", _mailbox(*mailbox))
    monitor.run(ctx)

    assert "Tie" in [call["sender"] for call in calls]


def test_graph_mail_pages_a_bounded_window_and_parks_before_the_last_message_read(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(monitor.notifications, "write_notification", lambda *a, **k: calls.append(k))
    monkeypatch.setattr(monitor.folders, "resolve_folder_id", lambda *a, **k: "inbox-id")

    now = datetime.now(UTC)
    mailbox = _oversized_window(now, monitor._MAX_WINDOW_MESSAGES)
    asked = {}

    def request_paginated(_conn, path, _account_id=None, params=None, limit=None, extra_prefer=None):
        asked.update(path=path, params=params, limit=limit)
        return iter(mailbox[:limit])

    monkeypatch.setattr(monitor.graph, "request_paginated", request_paginated)
    ctx = _run_ctx(tmp_path, cycles=1)
    acc = types.SimpleNamespace(username="me@x.com", account_id="acct-1")

    read_through = monitor._poll_graph_mail(ctx, acc, now, now - timedelta(hours=1), False)

    assert asked["params"]["$orderby"] == "receivedDateTime asc"
    assert asked["limit"] == monitor._MAX_WINDOW_MESSAGES
    assert len(calls) == monitor._MAX_WINDOW_MESSAGES
    assert read_through == datetime.fromisoformat(mailbox[-1]["receivedDateTime"]) - timedelta(seconds=1)
