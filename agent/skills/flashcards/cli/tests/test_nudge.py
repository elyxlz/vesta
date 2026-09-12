import json
from datetime import UTC, datetime, timedelta

from flashcards_cli import commands, nudge
from flashcards_cli.db import get_meta
from flashcards_cli.settings import Settings, set_setting, within_active_hours

from .conftest import NOON


def _notifications(notif_dir):
    return sorted(notif_dir.glob("*.json"))


def test_tick_writes_one_cards_due_notification_and_then_waits_out_the_interval(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    notif_dir = tmp_path / "notifications"
    commands.cards_add(conn, "spanish", [("a", "1", ""), ("b", "2", "")], now=NOON)
    commands.cards_add(conn, "anatomy", [("c", "3", "")], now=NOON)
    assert nudge.tick(conn, notif_dir, now=NOON) is True
    (path,) = _notifications(notif_dir)
    assert path.name.endswith("-flashcards-cards_due.json")
    notif = json.loads(path.read_text())
    assert (notif["source"], notif["type"], notif["interrupt"], notif["due_count"]) == ("flashcards", "cards_due", False, 3)
    assert notif["decks"] == "spanish 2, anatomy 1"
    assert "flashcards next" in notif["message"] and "timestamp" in notif
    assert nudge.tick(conn, notif_dir, now=NOON + timedelta(minutes=119)) is False
    assert nudge.tick(conn, notif_dir, now=NOON + timedelta(minutes=120)) is True
    assert len(_notifications(notif_dir)) == 2


def test_tick_is_silent_with_nothing_due_outside_active_hours_or_when_disabled(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    notif_dir = tmp_path / "notifications"
    assert nudge.tick(conn, notif_dir, now=NOON) is False
    commands.cards_add(conn, "spanish", [("a", "1", "")], now=NOON)
    assert nudge.tick(conn, notif_dir, now=NOON.replace(hour=23)) is False
    set_setting(conn, "nudge_interval_minutes", "0")
    assert nudge.tick(conn, notif_dir, now=NOON) is False
    assert _notifications(notif_dir) == []


def test_last_nudge_is_persisted_so_a_restart_does_not_nudge_again(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    notif_dir = tmp_path / "notifications"
    commands.cards_add(conn, "spanish", [("a", "1", "")], now=NOON)
    assert nudge.tick(conn, notif_dir, now=NOON) is True
    assert get_meta(conn, nudge.LAST_NUDGE_KEY) == "2026-03-02T12:00:00+00:00"
    assert nudge.tick(conn, notif_dir, now=NOON + timedelta(minutes=5)) is False


def test_active_hours_window_wraps_midnight():
    evening = Settings(active_hours="22:00-06:00")
    assert within_active_hours(evening, datetime(2026, 1, 1, 23, 30, tzinfo=UTC))
    assert within_active_hours(evening, datetime(2026, 1, 1, 5, 59, tzinfo=UTC))
    assert not within_active_hours(evening, datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    day = Settings()
    assert within_active_hours(day, datetime(2026, 1, 1, 9, 0, tzinfo=UTC))
    assert not within_active_hours(day, datetime(2026, 1, 1, 21, 0, tzinfo=UTC))
