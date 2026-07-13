"""Monitor behavior: catch-up clamping and one-shot surfacing of terminal auth failures."""

import json
import logging
import threading
from datetime import datetime, timedelta, UTC

from google_cli import calendar, monitor
from google_cli.config import Config
from google_cli.context import GoogleContext


def test_recent_last_check_is_left_untouched():
    now = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)
    last_check = now - timedelta(seconds=45)
    assert monitor.clamp_catchup_start(last_check, now) == last_check


def test_gap_within_the_window_is_left_untouched():
    now = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)
    last_check = now - timedelta(hours=6)
    assert monitor.clamp_catchup_start(last_check, now) == last_check


def test_stale_last_check_is_clamped_to_the_lookback_bound():
    now = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)
    last_check = now - timedelta(weeks=6)
    assert monitor.clamp_catchup_start(last_check, now) == now - monitor.MAX_CATCHUP_LOOKBACK


def test_clamp_bound_is_24_hours():
    assert monitor.MAX_CATCHUP_LOOKBACK == timedelta(hours=24)


# -- one-shot surfacing of terminal failures --------------------------------


def _ctx(tmp_path) -> GoogleContext:
    base = tmp_path / "monitor"
    base.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("test.google.monitor")
    logger.addHandler(logging.NullHandler())
    return GoogleContext(
        config=Config(data_dir=tmp_path / "data", log_dir=tmp_path / "logs"),
        notif_dir=tmp_path / "notifications",
        monitor_base_dir=base,
        monitor_state_file=base / "state.txt",
        monitor_log_file=tmp_path / "monitor.log",
        monitor_logger=logger,
        monitor_stop_event=threading.Event(),
    )


def _notif_files(ctx, notif_type):
    if not ctx.notif_dir.exists():
        return []
    return sorted(ctx.notif_dir.glob(f"*google-{notif_type}.json"))


def test_notify_broken_once_writes_a_single_interrupt_notification(tmp_path):
    ctx = _ctx(tmp_path)
    error = ValueError("Token refresh failed. run 'google auth login' to sign in again.")

    monitor.notify_broken_once(ctx, monitor.AUTH_BROKEN_MARKER, "auth_broken", error)
    monitor.notify_broken_once(ctx, monitor.AUTH_BROKEN_MARKER, "auth_broken", error)

    files = _notif_files(ctx, "auth_broken")
    assert len(files) == 1
    payload = json.loads(files[0].read_text())
    assert payload["source"] == "google"
    assert payload["type"] == "auth_broken"
    assert payload["interrupt"] is True
    assert "google auth login" in payload["error"]


def test_clear_broken_marker_rearms_the_notification(tmp_path):
    ctx = _ctx(tmp_path)
    error = ValueError("Not authenticated. Run 'google auth login' first.")

    monitor.notify_broken_once(ctx, monitor.AUTH_BROKEN_MARKER, "auth_broken", error)
    monitor.clear_broken_marker(ctx, monitor.AUTH_BROKEN_MARKER)  # auth recovered
    monitor.clear_broken_marker(ctx, monitor.AUTH_BROKEN_MARKER)  # idempotent
    monitor.notify_broken_once(ctx, monitor.AUTH_BROKEN_MARKER, "auth_broken", error)  # broke again later

    assert len(_notif_files(ctx, "auth_broken")) == 2


def test_run_surfaces_terminal_auth_failure_once_and_keeps_quiet(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)

    def broken_auth(config):
        ctx.monitor_stop_event.set()
        raise ValueError("Token refresh failed. run 'google auth login' to sign in again.")

    monkeypatch.setattr(monitor.api, "gmail_service", broken_auth)

    monitor.run(ctx)
    assert len(_notif_files(ctx, "auth_broken")) == 1

    # A later cycle (e.g. daemon restart) with auth still broken stays quiet.
    ctx.monitor_stop_event.clear()
    monitor.run(ctx)
    assert len(_notif_files(ctx, "auth_broken")) == 1


class _FakeGmail:
    """Minimal chainable gmail service returning an empty inbox."""

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kwargs):
        return self

    def execute(self):
        return {"messages": []}


def test_run_surfaces_calendar_auth_error_once_while_gmail_works(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(monitor.api, "gmail_service", lambda config: _FakeGmail())

    def broken_calendar(config, **kwargs):
        ctx.monitor_stop_event.set()
        raise calendar.CalendarAuthError("token was minted under the shared Thunderbird client; run 'google auth login'")

    monkeypatch.setattr(monitor.calendar, "list_events_between", broken_calendar)

    monitor.run(ctx)
    ctx.monitor_stop_event.clear()
    monitor.run(ctx)

    files = _notif_files(ctx, "calendar_auth_broken")
    assert len(files) == 1
    payload = json.loads(files[0].read_text())
    assert payload["interrupt"] is True
    assert "google auth login" in payload["error"]
    # Gmail auth is fine, so the auth_broken path never fired.
    assert _notif_files(ctx, "auth_broken") == []
