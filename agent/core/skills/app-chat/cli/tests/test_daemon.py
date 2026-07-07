"""Tests for the app-chat daemon's notification dedup + reconnect replay.

These pin the fix for silently-lost user messages: the dedup watermark must advance only on user
messages, so an assistant/tool/status event can never push it past an un-notified message and make
reconnect replay skip it.
"""

import json
import pathlib as pl

import app_chat_cli.daemon as daemon


def _state(tmp_path: pl.Path) -> daemon.DaemonState:
    notifications = tmp_path / "notifications"
    data = tmp_path / "data"
    notifications.mkdir(exist_ok=True)
    data.mkdir(exist_ok=True)
    return daemon.DaemonState(
        notifications_dir=notifications,
        ws_url="ws://x/ws",
        sock_path=data / "app-chat.sock",
        data_dir=data,
    )


def _messages(state: daemon.DaemonState) -> list[str]:
    # Filenames are random uuids, so glob order is arbitrary — sort for deterministic assertions.
    return sorted(json.loads(p.read_text())["message"] for p in state.notifications_dir.glob("*.json"))


def _user(ts: str, text: str) -> str:
    return json.dumps({"type": "user", "ts": ts, "text": text})


def _assistant(ts: str, text: str) -> str:
    return json.dumps({"type": "assistant", "ts": ts, "text": text})


def _snapshot(events: list[dict[str, object]]) -> str:
    return json.dumps({"type": "snapshot", "chat": {"events": events}})


def test_live_user_message_writes_one_notification(tmp_path):
    state = _state(tmp_path)
    daemon._handle_event(state, _user("t1", "hello"))
    assert _messages(state) == ["hello"]
    assert state.last_seen_ts == "t1"


def test_assistant_events_do_not_advance_watermark(tmp_path):
    state = _state(tmp_path)
    daemon._handle_event(state, _user("t1", "first"))
    daemon._handle_event(state, _assistant("t9", "a long streamed reply"))
    # The watermark tracks the last notified user message, not the latest event of any type.
    assert state.last_seen_ts == "t1"


def test_reconnect_replays_message_that_arrived_during_a_drop(tmp_path):
    # Regression: a user message (t3) arrives while disconnected; assistant activity (t9) happened
    # before the drop. If the watermark had advanced to t9, replay would skip t3 and lose it.
    state = _state(tmp_path)
    daemon._handle_event(state, _user("t1", "before drop"))
    daemon._handle_event(state, _assistant("t9", "reply that raced ahead"))

    daemon._handle_event(
        state,
        _snapshot(
            [{"type": "user", "ts": "t3", "text": "sent during drop"}, {"type": "assistant", "ts": "t9", "text": "reply that raced ahead"}]
        ),
    )

    assert _messages(state) == ["before drop", "sent during drop"]
    assert state.last_seen_ts == "t3"


def test_replay_skips_already_notified_messages(tmp_path):
    state = _state(tmp_path)
    daemon._handle_event(state, _user("t1", "hello"))

    daemon._handle_event(state, _snapshot([{"type": "user", "ts": "t1", "text": "hello"}]))

    assert _messages(state) == ["hello"]


def test_snapshot_live_overlap_does_not_double_notify(tmp_path):
    # The overlap window on connect can deliver the same user message in both the snapshot and live.
    state = _state(tmp_path)
    daemon._handle_event(state, _snapshot([{"type": "user", "ts": "t2", "text": "overlap"}]))
    daemon._handle_event(state, _user("t2", "overlap"))

    assert _messages(state) == ["overlap"]


def test_watermark_persists_across_restart(tmp_path):
    state = _state(tmp_path)
    daemon._handle_event(state, _user("t5", "hello"))

    reloaded = _state(tmp_path)
    daemon._load_last_seen_ts(reloaded)
    assert reloaded.last_seen_ts == "t5"
    # After restart, the snapshot must not re-notify the already-seen message.
    daemon._handle_event(reloaded, _snapshot([{"type": "user", "ts": "t5", "text": "hello"}]))
    assert _messages(reloaded) == ["hello"]


def test_message_without_ts_is_notified(tmp_path):
    state = _state(tmp_path)
    daemon._handle_event(state, json.dumps({"type": "user", "text": "no ts"}))
    assert _messages(state) == ["no ts"]
