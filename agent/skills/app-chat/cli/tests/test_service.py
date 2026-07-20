"""Tests for the app-chat service: POST /message intake (persist + emit + notification, intent_id
dedup, validation), GET /history paging, and GET /ws (the replay-free live chat stream). The live echo
now fans out in-process to connected /ws subscribers, so a test attaches its own subscriber queue (or a
real websocket) to observe it, standing independent of core's bus (Task 9)."""

import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer
from app_chat_cli.service import ServiceState, create_app
from app_chat_cli.store import Store, StoredEvent, store_path


def _service_state(tmp_path):
    store = Store(store_path(tmp_path / "data"))
    notif_dir = tmp_path / "notifications"
    return ServiceState(store, notif_dir), notif_dir


def _subscribe(state) -> "asyncio.Queue[StoredEvent]":
    queue: asyncio.Queue[StoredEvent] = asyncio.Queue()
    state.subscribers.add(queue)
    return queue


def _drain(queue) -> list[StoredEvent]:
    events: list[StoredEvent] = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


async def _wait_for(predicate) -> None:
    """Poll a condition to a bounded deadline (the ws handler registers/discards its subscriber a beat
    after the client handshake resolves; polling makes the assertion deterministic without a sleep)."""
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not met before the deadline")


async def _with_client(state, scenario):
    server = TestServer(create_app(state))
    client = TestClient(server)
    await client.start_server()
    try:
        return await scenario(client)
    finally:
        await client.close()


def _post(state, payload=None, *, data=None):
    async def scenario(client):
        resp = await client.post("/message", json=payload) if data is None else await client.post("/message", data=data)
        return resp.status, await resp.json()

    return asyncio.run(_with_client(state, scenario))


def test_message_persists_emits_and_writes_notification(tmp_path):
    state, notif_dir = _service_state(tmp_path)
    queue = _subscribe(state)

    status, body = _post(state, {"text": "hello there"})

    assert status == 200
    assert body == {"ok": True, "id": 1}
    events, _ = state.store.page()
    assert [(e["id"], e["type"], e["text"]) for e in events] == [(1, "user", "hello there")]
    emitted = _drain(queue)
    assert len(emitted) == 1 and emitted[0]["id"] == 1 and emitted[0]["text"] == "hello there"
    files = list(notif_dir.glob("*-app-chat-message.json"))
    assert len(files) == 1
    notif = json.loads(files[0].read_text())
    assert notif["source"] == "app-chat"
    assert notif["type"] == "message"
    assert notif["message"] == "hello there"
    assert notif["interrupt"] is True
    assert "reply_hint" in notif
    state.store.close()


def test_duplicate_intent_id_is_dropped_whole(tmp_path):
    state, notif_dir = _service_state(tmp_path)
    queue = _subscribe(state)

    async def scenario(client):
        first = await (await client.post("/message", json={"text": "hi", "intent_id": "abc"})).json()
        second = await (await client.post("/message", json={"text": "hi", "intent_id": "abc"})).json()
        return first, second

    first, second = asyncio.run(_with_client(state, scenario))

    assert first == {"ok": True, "id": 1}
    assert second == {"ok": True, "deduped": True}
    assert len(_drain(queue)) == 1
    assert len(state.store.page()[0]) == 1
    assert len(list(notif_dir.glob("*-app-chat-message.json"))) == 1
    state.store.close()


def test_intent_id_rides_along_on_the_event_and_notification(tmp_path):
    state, notif_dir = _service_state(tmp_path)
    queue = _subscribe(state)

    _post(state, {"text": "hi", "intent_id": "xyz"})

    assert _drain(queue)[0]["intent_id"] == "xyz"
    notif = json.loads(next(iter(notif_dir.glob("*-app-chat-message.json"))).read_text())
    assert notif["intent_id"] == "xyz"
    state.store.close()


def test_input_method_is_recorded_when_valid(tmp_path):
    state, _ = _service_state(tmp_path)
    queue = _subscribe(state)

    _post(state, {"text": "hey", "input_method": "voice"})

    events, _ = state.store.page()
    assert events[0]["input_method"] == "voice"
    assert _drain(queue)[0]["input_method"] == "voice"
    state.store.close()


def test_empty_text_is_rejected(tmp_path):
    state, notif_dir = _service_state(tmp_path)
    queue = _subscribe(state)

    status, body = _post(state, {"text": "   "})

    assert status == 400
    assert "error" in body
    assert _drain(queue) == []
    assert state.store.page()[0] == []
    assert not notif_dir.exists()
    state.store.close()


def test_missing_text_is_rejected(tmp_path):
    state, _ = _service_state(tmp_path)
    status, body = _post(state, {"foo": "bar"})
    assert status == 400
    assert "error" in body
    state.store.close()


def test_invalid_json_body_is_rejected(tmp_path):
    state, _ = _service_state(tmp_path)
    status, body = _post(state, data="not json")
    assert status == 400
    assert "error" in body
    state.store.close()


def test_failed_notification_write_is_recoverable_on_retry(tmp_path):
    state, _ = _service_state(tmp_path)
    queue = _subscribe(state)
    blocker = tmp_path / "blocker"
    blocker.write_text("")  # a regular file, so mkdir of a dir under it raises OSError
    state.notifications_dir = blocker / "notifications"

    async def scenario(client):
        first = await client.post("/message", json={"text": "hi", "intent_id": "abc"})
        first_result = (first.status, await first.json())
        state.notifications_dir = tmp_path / "notifications"
        second = await client.post("/message", json={"text": "hi", "intent_id": "abc"})
        return first_result, (second.status, await second.json())

    (first_status, _), (second_status, second_body) = asyncio.run(_with_client(state, scenario))

    assert first_status == 500  # the failed write persisted, echoed, and remembered nothing
    assert second_status == 200 and second_body["ok"] is True and second_body["id"] == 1
    assert len(state.store.page()[0]) == 1  # persisted exactly once
    assert len(_drain(queue)) == 1  # echoed exactly once
    assert len(list((tmp_path / "notifications").glob("*-app-chat-message.json"))) == 1
    state.store.close()


def test_history_returns_events_and_cursor(tmp_path):
    state, _ = _service_state(tmp_path)
    for i in range(3):
        state.store.append({"type": "user", "ts": f"2026-01-01T00:00:0{i}", "text": f"m{i}"})

    async def scenario(client):
        resp = await client.get("/history?limit=2")
        return resp.status, await resp.json()

    status, body = asyncio.run(_with_client(state, scenario))

    assert status == 200
    assert [e["text"] for e in body["events"]] == ["m1", "m2"]
    assert body["cursor"] == 2
    state.store.close()


def test_history_rejects_invalid_limit(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        resp = await client.get("/history?limit=abc")
        return resp.status, await resp.json()

    status, body = asyncio.run(_with_client(state, scenario))
    assert status == 400
    assert "error" in body
    state.store.close()


def test_emit_fans_out_and_drops_oldest_when_a_subscriber_queue_is_full(tmp_path):
    state, _ = _service_state(tmp_path)
    queue: asyncio.Queue[StoredEvent] = asyncio.Queue(maxsize=3)
    state.subscribers.add(queue)

    for i in range(5):
        state.emit({"type": "chat", "ts": "t", "text": f"m{i}", "id": i})

    assert queue.qsize() == 3
    kept = [queue.get_nowait()["id"] for _ in range(3)]
    # the oldest two aged out; the queue holds the most recent three, in order
    assert kept == [2, 3, 4]
    state.store.close()


def test_ws_streams_events_appended_after_connect_without_replaying_history(tmp_path):
    state, _ = _service_state(tmp_path)
    state.store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "before connect"})

    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await _wait_for(lambda: len(state.subscribers) == 1)
        resp = await client.post("/message", json={"text": "after connect", "intent_id": "live-1"})
        assert resp.status == 200
        frame = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
        await ws.close()
        return frame

    frame = asyncio.run(_with_client(state, scenario))

    # the pre-connect event is never replayed; the first frame is the live echo of the new message
    assert frame["type"] == "user"
    assert frame["text"] == "after connect"
    assert frame["intent_id"] == "live-1"
    state.store.close()


def test_ws_streams_a_reply_emitted_after_connect(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await _wait_for(lambda: len(state.subscribers) == 1)
        reply: StoredEvent = {"type": "chat", "ts": "2026-01-01T00:00:00", "text": "the reply", "id": 7}
        state.emit(reply)
        frame = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
        await ws.close()
        return frame

    frame = asyncio.run(_with_client(state, scenario))

    assert frame == {"type": "chat", "ts": "2026-01-01T00:00:00", "text": "the reply", "id": 7}
    state.store.close()


def test_ws_disconnect_discards_the_subscriber(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await _wait_for(lambda: len(state.subscribers) == 1)
        await ws.close()
        await _wait_for(lambda: len(state.subscribers) == 0)
        return len(state.subscribers)

    remaining = asyncio.run(_with_client(state, scenario))

    assert remaining == 0
    state.store.close()
