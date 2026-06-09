"""Unit tests for monitor.clamp_catchup_start — bounding the first-run catch-up window."""

from datetime import datetime, timedelta, UTC

from google_cli import monitor


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
