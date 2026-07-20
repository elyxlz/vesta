"""Tests for the app-chat intake (notification write + intent-id dedup)."""

import json
import os
from pathlib import Path

import core.config as cfg
import core.models as vm
from core.app_chat_intake import _write_app_chat_notification


def test_app_chat_messages_delivered_in_send_order(config):
    """Two app-chat messages written in quick succession must be read back in send order. The
    monotonic time_ns() stem sorts lexically the same as send order; a uuid4 stem would not."""
    _write_app_chat_notification(config, "first")
    _write_app_chat_notification(config, "second")

    files = sorted(config.notifications_dir.glob("*.json"))
    assert len(files) == 2
    texts = [json.loads(f.read_text())["message"] for f in files]
    assert texts == ["first", "second"]


def test_write_app_chat_notification_never_exposes_partial_file(config, monkeypatch):
    """The write goes through atomic_write_text: a sibling .tmp file, then os.replace. A monitor
    tick globbing the notifications dir mid-write can only ever see the tmp file (excluded by the
    *.json glob) or the fully written target, never a truncated target."""
    observed_matches: list[list[Path]] = []
    real_replace = os.replace

    def spying_replace(src, dst):
        observed_matches.append(list(config.notifications_dir.glob("*.json")))
        real_replace(src, dst)

    monkeypatch.setattr(cfg.os, "replace", spying_replace)
    _write_app_chat_notification(config, "hello")

    assert observed_matches == [[]]  # no *.json match existed right before the rename
    files = list(config.notifications_dir.glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text())["message"] == "hello"


def test_write_app_chat_notification_stores_intent_id(config):
    """The intake helper persists a provided intent_id as a notification field."""
    _write_app_chat_notification(config, "hello", "intent-xyz")
    files = list(config.notifications_dir.glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text())["intent_id"] == "intent-xyz"


def test_remember_intent_bounds_the_seen_set():
    """The seen-intent set is a bounded FIFO: past the cap the oldest intent ages out, the newest stay."""
    from core.app_chat_intake import _SEEN_INTENT_IDS_CAP, _remember_intent

    state = vm.State()
    for i in range(_SEEN_INTENT_IDS_CAP + 10):
        _remember_intent(state, f"intent-{i}")
    assert len(state.seen_intent_ids) == _SEEN_INTENT_IDS_CAP
    assert "intent-0" not in state.seen_intent_ids  # oldest evicted
    assert f"intent-{_SEEN_INTENT_IDS_CAP + 9}" in state.seen_intent_ids  # newest kept
