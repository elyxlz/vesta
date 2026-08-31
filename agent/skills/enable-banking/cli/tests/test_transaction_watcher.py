"""Behavior-locking tests for the transaction watcher's notification write path."""

import json
import sys
import types
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


def pending(reference, amount, details="Coffee Shop"):
    return {
        "entry_reference": reference,
        "booking_date": "2026-08-30",
        "status": "PDNG",
        "transaction_amount": {"amount": amount, "currency": "GBP"},
        "remittance_information_unstructured": details,
        "credit_debit_indicator": "DBIT",
    }


def run_poll(tmp_path, monkeypatch, batches):
    """Drive poll_once over successive provider responses against one seen file."""
    monkeypatch.setattr(tw, "SEEN_FILE", tmp_path / "seen_transactions.json")
    module = types.ModuleType("finance_cli.enablebanking")
    pending_batches = list(batches)
    module.get_transactions = lambda *args, **kwargs: pending_batches.pop(0)
    monkeypatch.setitem(sys.modules, "finance_cli.enablebanking", module)
    monkeypatch.setattr(tw.Path, "home", staticmethod(lambda: tmp_path))
    config = tmp_path / ".finance" / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"session_id": "s", "accounts": [{"uid": "a", "currency": "GBP"}]}))
    return [tw.poll_once() for _ in batches]


def test_id_is_the_provider_reference_when_there_is_one():
    """The amount must stay out of the identity: a pending authorisation mutates its amount in
    place while keeping its reference, and an amount in the key makes that read as a new charge."""
    reference = "6a93f9da-32c0-aabf-92ec-971c6ea9b82f"
    assert tw.make_tx_id(pending(reference, "88.67")) == reference
    assert tw.make_tx_id(pending(reference, "25.76")) == reference


def test_id_falls_back_to_the_composite_without_a_reference():
    tx = pending("", "12.50")
    assert tw.make_tx_id(tx) == "-2026-08-30-12.50"
    assert tw.make_tx_id(pending("", "9.99")) != tw.make_tx_id(tx)


def test_revised_pending_amount_is_reported_as_a_revision_not_a_new_transaction(tmp_path, monkeypatch):
    reference = "6a93f9da-32c0-aabf-92ec-971c6ea9b82f"
    first, second = run_poll(tmp_path, monkeypatch, [[pending(reference, "88.67")], [pending(reference, "25.76")]])

    assert [tw.notification_message(tx) for tx in first] == ["New transaction: -£88.67 — Coffee Shop"]
    (revision,) = second
    assert revision["_previous_amount"] == "88.67"
    message = tw.notification_message(revision)
    assert "£25.76" in message and "£88.67" in message
    assert not message.startswith("New transaction")


def test_unchanged_pending_transaction_is_silent(tmp_path, monkeypatch):
    reference = "6a93f9da-32c0-aabf-92ec-971c6ea9b82f"
    _, second, third = run_poll(tmp_path, monkeypatch, [[pending(reference, "88.67")]] * 3)
    assert second == [] and third == []


def test_a_genuinely_new_reference_still_notifies(tmp_path, monkeypatch):
    old, new = "6a93f9da-32c0-aabf-92ec-971c6ea9b82f", "1b0c77ae-5d21-4f0a-9a3c-2f1e6d4b8c90"
    _, second = run_poll(tmp_path, monkeypatch, [[pending(old, "88.67")], [pending(old, "88.67"), pending(new, "4.20")]])
    assert [tx["entry_reference"] for tx in second] == [new]
    assert tw.notification_message(second[0]) == "New transaction: -£4.20 — Coffee Shop"


def test_a_legacy_seen_file_does_not_cause_a_re_notification_storm(tmp_path, monkeypatch):
    """The failure mode worse than the bug: composite ids left unrecognised by the new keying would
    re-notify every historical transaction at once, so they are migrated on load."""
    seen_file = tmp_path / "seen_transactions.json"
    history = [pending(f"ref-{n}-uuid", f"{n}.00") for n in range(20)]
    seen_file.write_text(json.dumps([f"{tx['entry_reference']}-2026-08-30-{tx['transaction_amount']['amount']}" for tx in history]))

    (polled,) = run_poll(tmp_path, monkeypatch, [history])
    assert polled == []
    assert set(json.loads(seen_file.read_text())) == {tx["entry_reference"] for tx in history}


def test_a_migrated_id_still_catches_a_later_revision(tmp_path, monkeypatch):
    reference = "6a93f9da-32c0-aabf-92ec-971c6ea9b82f"
    seen_file = tmp_path / "seen_transactions.json"
    seen_file.write_text(json.dumps([f"{reference}-2026-08-30-88.67"]))

    (revised,) = run_poll(tmp_path, monkeypatch, [[pending(reference, "25.76")]])
    assert [tx.get("_previous_amount") for tx in revised] == ["88.67"]


def test_seed_seen_keys_the_file_the_same_way_as_the_poller(tmp_path, monkeypatch):
    reference = "6a93f9da-32c0-aabf-92ec-971c6ea9b82f"
    seen_file = tmp_path / "seen_transactions.json"
    monkeypatch.setattr(tw, "SEEN_FILE", seen_file)
    module = types.ModuleType("finance_cli.enablebanking")
    module.get_transactions = lambda *args, **kwargs: [pending(reference, "88.67")]
    monkeypatch.setitem(sys.modules, "finance_cli.enablebanking", module)
    monkeypatch.setattr(tw.Path, "home", staticmethod(lambda: tmp_path))
    config = tmp_path / ".finance" / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"session_id": "s", "accounts": [{"uid": "a", "currency": "GBP"}]}))

    tw.seed_seen()
    assert json.loads(seen_file.read_text()) == {reference: "88.67"}
    assert tw.poll_once() == []


def test_write_notification_carries_the_revision_wording(tmp_path, monkeypatch):
    monkeypatch.setattr(tw, "NOTIFICATIONS_DIR", tmp_path / "notifications")
    tx = pending("ref", "25.76") | {"_previous_amount": "88.67"}
    tw.write_notification(tx)
    (written,) = (tmp_path / "notifications").iterdir()
    message = json.loads(written.read_text())["message"]
    assert "£25.76" in message and "£88.67" in message and "New transaction" not in message
