"""Monitor behavior: catch-up clamping, one-shot surfacing of terminal auth failures, and
per-unit watermark recovery across an outage window (a failed poll must not skip its window)."""

import json
import logging
import threading
import types
from datetime import UTC, datetime, timedelta

import httplib2
from google_cli import calendar, monitor
from google_cli.config import Config
from google_cli.context import GoogleContext
from googleapiclient.errors import HttpError


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
    assert timedelta(hours=24) == monitor.MAX_CATCHUP_LOOKBACK


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


# -- outage-gap recovery: a failed poll parks its own watermark ---------------


def _http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b'{"error": "outage"}')


def _gmail_message(sender: str, subject: str, snippet: str) -> dict:
    return {"payload": {"headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}]}, "snippet": snippet}


class _DrivenGmail:
    """Chainable gmail stub honoring the real service's contract: list() runs list_hook (which may
    raise HttpError to simulate an outage), then returns the inbox filtered by the query's ``after:``
    epoch, exactly as Gmail's server-side filter does; get() returns the message for the fetched id."""

    def __init__(self, inbox: list[tuple[str, datetime]], list_hook, messages_by_id: dict[str, dict]) -> None:
        self._inbox = inbox
        self._list_hook = list_hook
        self._messages_by_id = messages_by_id
        self._op = ""
        self._query = ""
        self._get_id = ""

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kwargs):
        self._op = "list"
        self._query = kwargs["q"]
        return self

    def get(self, **kwargs):
        self._op = "get"
        self._get_id = kwargs["id"]
        return self

    def execute(self):
        if self._op == "list":
            self._list_hook()
            after = int(self._query.removeprefix("after:"))
            return {"messages": [{"id": mid} for mid, arrived in self._inbox if int(arrived.timestamp()) > after]}
        return self._messages_by_id[self._get_id]


def _run_ctx(tmp_path, cycles: int):
    """A context whose stop event ends run() after ``cycles`` iterations."""
    remaining = {"cycles": cycles}

    def wait(_timeout):
        remaining["cycles"] -= 1
        return remaining["cycles"] <= 0

    base = tmp_path / "monitor"
    base.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("test.google.monitor.run")
    logger.addHandler(logging.NullHandler())
    return types.SimpleNamespace(
        config=types.SimpleNamespace(get_calendar_notify_thresholds=lambda: [10080, 60, 15]),
        notif_dir=tmp_path / "notifications",
        monitor_base_dir=base,
        monitor_state_file=base / "state.txt",
        monitor_logger=logger,
        monitor_stop_event=types.SimpleNamespace(is_set=lambda: False, wait=wait),
    )


def _watermark(ctx, unit: str) -> datetime:
    return datetime.fromisoformat(json.loads(ctx.monitor_state_file.read_text())["units"][unit])


def _email_notifs(calls: list[dict]) -> list[str]:
    return [call["subject"] for call in calls if "subject" in call]


def test_failed_gmail_poll_recovers_the_outage_window_next_cycle(tmp_path, monkeypatch):
    """The issue's exact case: a poll that failed on a dead token does not advance the watermark, so
    the next healthy cycle re-reads the window and surfaces the mail that arrived during the outage."""
    calls = []
    monkeypatch.setattr(monitor.notifications, "write_notification", lambda *a, **k: calls.append(k))
    monkeypatch.setattr(monitor.calendar, "list_events_between", lambda *a, **k: [])

    now = datetime.now(UTC)
    arrived_at = now - timedelta(seconds=30)
    ctx = _run_ctx(tmp_path, cycles=2)
    ctx.monitor_state_file.write_text((now - timedelta(seconds=60)).isoformat())

    cycle = {"n": 0}

    def list_hook():
        cycle["n"] += 1
        if cycle["n"] == 1:
            raise _http_error(503)

    inbox = [("m1", arrived_at)]
    messages_by_id = {"m1": _gmail_message("Manager <boss@x.com>", "Q3 plan", "please review")}
    monkeypatch.setattr(monitor.api, "gmail_service", lambda config: _DrivenGmail(inbox, list_hook, messages_by_id))

    monitor.run(ctx)

    # Notified exactly once (no skip from the failed cycle, no duplicate from the recovery).
    assert _email_notifs(calls) == ["Q3 plan"]
    assert _watermark(ctx, "mail") > arrived_at


def test_broken_calendar_does_not_make_mail_renotify(tmp_path, monkeypatch):
    """Guards the per-unit granularity: a single shared watermark parked by a terminally broken
    calendar would re-notify mail's whole window every cycle. Separate watermarks keep them apart."""
    calls = []
    monkeypatch.setattr(monitor.notifications, "write_notification", lambda *a, **k: calls.append(k))

    def broken_calendar(*_args, **_kwargs):
        raise calendar.CalendarAuthError("Calendar API disabled for this client; run 'google auth login'")

    monkeypatch.setattr(monitor.calendar, "list_events_between", broken_calendar)

    now = datetime.now(UTC)
    ctx = _run_ctx(tmp_path, cycles=2)
    ctx.monitor_state_file.write_text((now - timedelta(seconds=60)).isoformat())

    inbox = [("m1", now - timedelta(seconds=30))]
    messages_by_id = {"m1": _gmail_message("Colleague <c@x.com>", "hello", "hi there")}
    monkeypatch.setattr(monitor.api, "gmail_service", lambda config: _DrivenGmail(inbox, lambda: None, messages_by_id))

    monitor.run(ctx)

    # Mail is notified once, not once per cycle; calendar stays parked behind mail.
    assert _email_notifs(calls) == ["hello"]
    assert _watermark(ctx, "calendar") < _watermark(ctx, "mail")


def test_legacy_bare_timestamp_state_is_read_as_the_starting_watermark(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(monitor.notifications, "write_notification", lambda *a, **k: calls.append(k))
    monkeypatch.setattr(monitor.calendar, "list_events_between", lambda *a, **k: [])

    now = datetime.now(UTC)
    ctx = _run_ctx(tmp_path, cycles=1)
    ctx.monitor_state_file.write_text((now - timedelta(minutes=5)).isoformat())

    inbox = [("before", now - timedelta(minutes=10)), ("after", now - timedelta(minutes=2))]
    messages_by_id = {
        "before": _gmail_message("Before <b@x.com>", "before", "x"),
        "after": _gmail_message("After <a@x.com>", "after", "y"),
    }
    monkeypatch.setattr(monitor.api, "gmail_service", lambda config: _DrivenGmail(inbox, lambda: None, messages_by_id))

    monitor.run(ctx)

    assert _email_notifs(calls) == ["after"]
