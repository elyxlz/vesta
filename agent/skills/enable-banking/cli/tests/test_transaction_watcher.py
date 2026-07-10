"""Behavior-locking tests for the transaction watcher's notification write path."""

import json

from finance_cli import transaction_watcher as tw


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
