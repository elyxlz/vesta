"""The watcher's health record and daemon_unhealthy notification (finance_cli.health).

The rules under test are the daemon contract's (skills/vestad/SKILL.md): a permanent failure is
news on first sight, a transient one earns retries first, the notified-state lives on disk so a
restart never re-announces, one reminder a day while still broken, and a success re-arms it all.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from finance_cli import health

T0 = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "HEALTH_FILE", tmp_path / "daemons" / "finance.health")
    monkeypatch.setattr(health, "NOTIFICATIONS_DIR", tmp_path / "notifications")
    return tmp_path


def _notices(dirs) -> list[dict]:
    directory = dirs / "notifications"
    if not directory.exists():
        return []
    return [json.loads(path.read_text()) for path in sorted(directory.glob("*.json"))]


def test_no_record_means_no_opinion(dirs):
    assert health.read_health() is None


def test_a_success_writes_a_healthy_record(dirs):
    health.record_success(now=T0)
    recorded = health.read_health()
    assert recorded == health.Health(
        healthy=True, last_success_at="2026-08-01T12:00:00+00:00", consecutive_failures=0, error=None, notified_at=None
    )
    assert _notices(dirs) == []


def test_a_transient_failure_is_not_announced_until_it_persists(dirs):
    health.record_success(now=T0)
    for tick in range(1, health.UNHEALTHY_AFTER_FAILURES):
        health.record_failure("503 from upstream", permanent=False, now=T0 + timedelta(minutes=5 * tick))
        assert _notices(dirs) == [], f"a blip was announced on failure {tick}"
    recorded = health.read_health()
    assert recorded is not None
    assert recorded.healthy is False
    assert recorded.consecutive_failures == health.UNHEALTHY_AFTER_FAILURES - 1
    assert recorded.last_success_at == "2026-08-01T12:00:00+00:00"
    assert recorded.error == "503 from upstream"

    health.record_failure("503 from upstream", permanent=False, now=T0 + timedelta(hours=1))
    notices = _notices(dirs)
    assert len(notices) == 1
    assert notices[0]["type"] == "daemon_unhealthy"
    assert notices[0]["source"] == "finance"
    assert notices[0]["interrupt"] is True
    assert "503 from upstream" in notices[0]["message"]
    assert "2026-08-01T12:00:00+00:00" in notices[0]["message"]


def test_a_permanent_failure_is_announced_on_first_sight(dirs):
    health.record_success(now=T0)
    health.record_failure("status 401, credential revoked", permanent=True, now=T0 + timedelta(minutes=5))
    notices = _notices(dirs)
    assert len(notices) == 1
    assert "401" in notices[0]["message"]


def test_the_announcement_is_not_repeated_within_a_day_even_across_restarts(dirs):
    """The suppression lives in the record, not the process: nothing here holds state between
    calls, so every call after the first is what a freshly restarted watcher would do."""
    health.record_failure("status 401", permanent=True, now=T0)
    for hours in (1, 6, 23):
        health.record_failure("status 401", permanent=True, now=T0 + timedelta(hours=hours))
    assert len(_notices(dirs)) == 1


def test_a_failure_still_standing_a_day_later_is_announced_again(dirs):
    health.record_failure("status 401", permanent=True, now=T0)
    health.record_failure("status 401", permanent=True, now=T0 + timedelta(seconds=health.RENOTIFY_SECS))
    assert len(_notices(dirs)) == 2


def test_a_success_re_arms_the_announcement(dirs):
    health.record_failure("status 401", permanent=True, now=T0)
    health.record_success(now=T0 + timedelta(hours=1))
    health.record_failure("status 401", permanent=True, now=T0 + timedelta(hours=2))
    assert len(_notices(dirs)) == 2


def test_a_corrupt_record_reads_as_no_opinion_and_counting_restarts(dirs):
    health.HEALTH_FILE.parent.mkdir(parents=True)
    health.HEALTH_FILE.write_text("not json{")
    assert health.read_health() is None
    health.record_failure("boom", permanent=False, now=T0)
    recorded = health.read_health()
    assert recorded is not None
    assert recorded.consecutive_failures == 1
