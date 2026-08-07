"""Behavior-locking tests for the transaction watcher's notification write path."""

import json
from pathlib import Path

from finance_cli import transaction_watcher as tw


def test_notifications_go_to_the_directory_the_engine_watches():
    """A notification written into any other directory still succeeds: no exception, no log line,
    only silence, which is indistinguishable from a watcher with nothing to say. The engine watches
    ~/agent/notifications, so the destination is locked here."""
    engine_dir = Path.home() / "agent" / "notifications"
    assert engine_dir == tw.NOTIFICATIONS_DIR


def test_atomic_write_creates_parent_and_leaves_no_tmp(tmp_path):
    target = tmp_path / "notifications" / "hello.json"
    tw.atomic_write_text(target, '{"ok": true}')
    assert target.read_text() == '{"ok": true}'
    assert list(target.parent.iterdir()) == [target]


def test_write_notification_lands_fully_written_pooled_json(tmp_path, monkeypatch):
    notifications_dir = tmp_path / "notifications"
    monkeypatch.setattr(tw, "NOTIFICATIONS_DIR", notifications_dir)

    tx = {
        "transaction_amount": {"amount": "12.50", "currency": "GBP"},
        "remittance_information_unstructured": "Coffee Shop",
        "credit_debit_indicator": "DBIT",
    }
    tw.write_notification(tx)

    files = list(notifications_dir.iterdir())
    assert len(files) == 1
    assert files[0].name.endswith("-finance-message.json")
    notification = json.loads(files[0].read_text())
    assert notification["type"] == "finance"
    assert notification["source"] == "finance"
    assert notification["interrupt"] is False
    assert notification["message"] == "New transaction: -£12.50 — Coffee Shop"


def test_successive_notification_filenames_sort_in_send_order(tmp_path, monkeypatch):
    notifications_dir = tmp_path / "notifications"
    monkeypatch.setattr(tw, "NOTIFICATIONS_DIR", notifications_dir)

    written_order = []
    for detail in ("first", "second", "third"):
        tw.write_notification({"transaction_amount": {"amount": "1", "currency": "EUR"}, "remittance_information_unstructured": detail})
        (latest,) = [path for path in notifications_dir.iterdir() if path.name not in written_order]
        written_order.append(latest.name)

    assert sorted(written_order) == written_order


def _configured_home(tmp_path, monkeypatch):
    """A signed-in HOME for poll_once to read: one account, a session, an empty seen file."""
    monkeypatch.setenv("HOME", str(tmp_path))
    finance_dir = tmp_path / ".finance"
    finance_dir.mkdir()
    (finance_dir / "config.json").write_text(json.dumps({"session_id": "sess-1", "accounts": [{"uid": "acc-1", "currency": "GBP"}]}))
    monkeypatch.setattr(tw, "SEEN_FILE", finance_dir / "seen_transactions.json")
    tw.save_seen(set())


def test_an_api_error_during_a_poll_is_a_recorded_failure_not_a_process_death(tmp_path, monkeypatch):
    """The regression that killed the live watcher: one 503 from the provider ended the whole
    process, because the API layer's failure was not an Exception the poll loop could catch.
    Now it is: the cycle completes, classified transient, and the next cycle retries."""
    from finance_cli import enablebanking as eb

    _configured_home(tmp_path, monkeypatch)

    def upstream_sad(*_args, **_kwargs):
        raise eb.ApiError(503, "Enable Banking API error (GET x): status 503")

    monkeypatch.setattr(eb, "get_transactions", upstream_sad)
    outcome = tw.poll_once()
    assert outcome.attempted is True
    assert outcome.new_txs == []
    assert [failure.permanent for failure in outcome.failures] == [False]


def test_a_401_is_classified_permanent(tmp_path, monkeypatch):
    from finance_cli import enablebanking as eb

    _configured_home(tmp_path, monkeypatch)

    def credential_dead(*_args, **_kwargs):
        raise eb.ApiError(401, "Enable Banking API error (GET x): status 401")

    monkeypatch.setattr(eb, "get_transactions", credential_dead)
    outcome = tw.poll_once()
    assert [failure.permanent for failure in outcome.failures] == [True]


def test_an_unconfigured_watcher_polls_nothing_and_has_no_health_opinion(tmp_path, monkeypatch):
    """A watcher started before sign-in is idle, not unhealthy: it must not write a health
    record, or every fresh install would announce itself as broken."""
    from finance_cli import health

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(tw, "SEEN_FILE", tmp_path / ".finance" / "seen_transactions.json")
    monkeypatch.setattr(health, "HEALTH_FILE", tmp_path / "daemons" / "finance.health")
    tw.save_seen(set())

    outcome = tw.poll_once()
    assert outcome.attempted is False

    tw._tick()
    assert not health.HEALTH_FILE.exists()


def test_a_tick_records_its_outcome_in_the_health_record(tmp_path, monkeypatch):
    """The wiring the daemon contract's status half depends on: a failing cycle lands in the
    record as unhealthy, and a working one resets it to healthy."""
    from finance_cli import health

    monkeypatch.setattr(tw, "SEEN_FILE", tmp_path / "seen_transactions.json")
    monkeypatch.setattr(health, "HEALTH_FILE", tmp_path / "daemons" / "finance.health")
    monkeypatch.setattr(health, "NOTIFICATIONS_DIR", tmp_path / "notifications")
    tw.save_seen(set())

    failing = tw.PollOutcome([], [tw.PollFailure(error="status 401", permanent=True)], attempted=True)
    monkeypatch.setattr(tw, "poll_once", lambda: failing)
    tw._tick()
    recorded = health.read_health()
    assert recorded is not None
    assert recorded.healthy is False
    assert recorded.consecutive_failures == 1
    assert recorded.error == "status 401"
    assert len(list((tmp_path / "notifications").glob("*daemon_unhealthy*"))) == 1

    monkeypatch.setattr(tw, "poll_once", lambda: tw.PollOutcome([], [], attempted=True))
    tw._tick()
    recorded = health.read_health()
    assert recorded is not None
    assert recorded.healthy is True
    assert recorded.consecutive_failures == 0
