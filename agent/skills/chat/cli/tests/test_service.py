"""Tests for the chat service: POST /message intake (persist + emit + notification, intent_id
dedup, validation), GET /history paging, and GET /ws (the replay-free live chat stream). The live echo
now fans out in-process to connected /ws subscribers, so a test attaches its own subscriber queue (or a
real websocket) to observe it, standing independent of core's bus (Task 9)."""

import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer
from chat_cli.service import ServiceState, create_app
from chat_cli.store import Store, StoredEvent, store_path


def _service_state(tmp_path):
    store = Store(store_path(tmp_path / "data"))
    notif_dir = tmp_path / "notifications"
    return ServiceState(store, notif_dir, tmp_path / "attachments"), notif_dir


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
    files = list(notif_dir.glob("*-chat-message.json"))
    assert len(files) == 1
    notif = json.loads(files[0].read_text())
    assert notif["source"] == "chat"
    assert notif["type"] == "message"
    assert notif["message"] == "hello there"
    assert notif["interrupt"] is True
    assert notif["reply_command"] == "chat send --message -"
    assert notif["reply_hint"] == "think about how you can best show your personality"
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
    assert len(list(notif_dir.glob("*-chat-message.json"))) == 1
    state.store.close()


def test_intent_id_stays_on_event_and_out_of_model_notification(tmp_path):
    state, notif_dir = _service_state(tmp_path)
    queue = _subscribe(state)

    _post(state, {"text": "hi", "intent_id": "xyz"})

    assert _drain(queue)[0]["intent_id"] == "xyz"
    notif = json.loads(next(iter(notif_dir.glob("*-chat-message.json"))).read_text())
    assert "intent_id" not in notif
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
    assert len(list((tmp_path / "notifications").glob("*-chat-message.json"))) == 1
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


def test_ws_speaking_frames_flip_the_flag_and_junk_is_ignored(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await _wait_for(lambda: len(state.subscribers) == 1)
        await ws.send_str(json.dumps({"type": "speaking", "active": True}))
        await _wait_for(lambda: bool(state.speaking))
        await ws.send_str("not json")
        await ws.send_str(json.dumps({"type": "unknown-frame"}))
        await ws.send_str(json.dumps({"type": "speaking", "active": "yes"}))
        assert state.speaking
        await ws.send_str(json.dumps({"type": "speaking", "active": False}))
        await _wait_for(lambda: not state.speaking)
        await ws.close()

    asyncio.run(_with_client(state, scenario))
    state.store.close()


def test_ws_disconnect_clears_a_live_speaking_flag(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await _wait_for(lambda: len(state.subscribers) == 1)
        await ws.send_str(json.dumps({"type": "speaking", "active": True}))
        await _wait_for(lambda: bool(state.speaking))
        await ws.close()
        await _wait_for(lambda: not state.speaking)

    asyncio.run(_with_client(state, scenario))
    state.store.close()


def test_ws_disconnect_after_a_refusal_writes_the_turn_end_notification(tmp_path):
    state, notif_dir = _service_state(tmp_path)

    async def scenario(client):
        ws = await client.ws_connect("/ws")
        await _wait_for(lambda: len(state.subscribers) == 1)
        await ws.send_str(json.dumps({"type": "speaking", "active": True}))
        await _wait_for(lambda: bool(state.speaking))
        assert state.refuse_send_while_speaking() is not None
        await ws.close()
        await _wait_for(lambda: not state.speaking)
        assert len(list(notif_dir.glob("*-chat-user_finished_talking.json"))) == 1

    asyncio.run(_with_client(state, scenario))
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


# --- attachment routes ---


async def _upload_via_routes(client, data: bytes, name="photo.jpg", mime="image/jpeg", chunks=None):
    created = await client.post("/attachments", json={"name": name, "mime": mime, "size": len(data)})
    assert created.status == 200
    attachment_id = (await created.json())["id"]
    offset = 0
    for chunk in chunks if chunks is not None else [data]:
        put = await client.put(f"/attachments/{attachment_id}/data?offset={offset}", data=chunk)
        assert put.status == 200
        offset += len(chunk)
    done = await client.post(f"/attachments/{attachment_id}/complete", json={})
    assert done.status == 200
    return attachment_id, await done.json()


def test_attachment_upload_round_trip_with_headers(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        attachment_id, done = await _upload_via_routes(client, b"abcdefgh", chunks=[b"abcd", b"efgh"])
        got = await client.get(f"/attachments/{attachment_id}")
        body = await got.read()
        return done, got, body

    done, got, body = asyncio.run(_with_client(state, scenario))

    attachment = done["attachment"]
    assert attachment["name"] == "photo.jpg"
    assert attachment["mime"] == "image/jpeg"
    assert attachment["size"] == 8
    assert body == b"abcdefgh"
    assert got.headers["Content-Type"] == "image/jpeg"
    assert got.headers["Content-Disposition"] == "inline; filename=\"photo.jpg\"; filename*=UTF-8''photo.jpg"
    assert got.headers["X-Content-Type-Options"] == "nosniff"
    assert got.headers["Content-Security-Policy"] == "sandbox"
    assert got.headers["Cache-Control"] == "private, max-age=3600"
    assert got.headers["Accept-Ranges"] == "bytes"
    state.store.close()


def test_attachment_create_rejects_oversize_declare(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        resp = await client.post("/attachments", json={"name": "big.bin", "mime": "application/octet-stream", "size": 10**12})
        return resp.status, await resp.json()

    status, body = asyncio.run(_with_client(state, scenario))
    assert status == 413
    assert "error" in body
    state.store.close()


def test_attachment_create_rejects_invalid_body(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        resp = await client.post("/attachments", json={"name": "x"})
        return resp.status

    assert asyncio.run(_with_client(state, scenario)) == 400
    state.store.close()


def test_attachment_stale_offset_answers_409_with_received(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        created = await client.post("/attachments", json={"name": "a.bin", "mime": "application/octet-stream", "size": 8})
        attachment_id = (await created.json())["id"]
        await client.put(f"/attachments/{attachment_id}/data?offset=0", data=b"abcd")
        stale = await client.put(f"/attachments/{attachment_id}/data?offset=2", data=b"xx")
        replay = await client.put(f"/attachments/{attachment_id}/data?offset=0", data=b"abcd")
        return (stale.status, await stale.json()), (replay.status, await replay.json())

    (stale_status, stale_body), (replay_status, replay_body) = asyncio.run(_with_client(state, scenario))

    assert stale_status == 409 and stale_body["received"] == 4
    assert replay_status == 409 and replay_body["received"] == 4  # == offset + len: delivered
    state.store.close()


def test_attachment_invalid_offset_is_rejected(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        created = await client.post("/attachments", json={"name": "a.bin", "mime": "application/octet-stream", "size": 8})
        attachment_id = (await created.json())["id"]
        resp = await client.put(f"/attachments/{attachment_id}/data?offset=abc", data=b"x")
        return resp.status

    assert asyncio.run(_with_client(state, scenario)) == 400
    state.store.close()


def test_attachment_status_reports_progress_and_finalized(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        created = await client.post("/attachments", json={"name": "a.bin", "mime": "application/octet-stream", "size": 8})
        attachment_id = (await created.json())["id"]
        await client.put(f"/attachments/{attachment_id}/data?offset=0", data=b"abcd")
        mid = await (await client.get(f"/attachments/{attachment_id}/status")).json()
        await client.put(f"/attachments/{attachment_id}/data?offset=4", data=b"efgh")
        await client.post(f"/attachments/{attachment_id}/complete", json={})
        done = await (await client.get(f"/attachments/{attachment_id}/status")).json()
        return mid, done

    mid, done = asyncio.run(_with_client(state, scenario))

    assert mid == {"received": 4, "size": 8, "finalized": False}
    assert done == {"received": 8, "size": 8, "finalized": True}
    state.store.close()


def test_attachment_complete_is_idempotent_and_verifies_size(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        created = await client.post("/attachments", json={"name": "a.bin", "mime": "application/octet-stream", "size": 4})
        attachment_id = (await created.json())["id"]
        short = await client.post(f"/attachments/{attachment_id}/complete", json={})
        await client.put(f"/attachments/{attachment_id}/data?offset=0", data=b"abcd")
        first = await (await client.post(f"/attachments/{attachment_id}/complete", json={})).json()
        second = await (await client.post(f"/attachments/{attachment_id}/complete", json={})).json()
        return short.status, first, second

    short_status, first, second = asyncio.run(_with_client(state, scenario))

    assert short_status == 409
    assert first == second
    state.store.close()


def test_attachment_unknown_id_is_404_everywhere(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        return (
            (await client.put("/attachments/nope/data?offset=0", data=b"x")).status,
            (await client.get("/attachments/nope/status")).status,
            (await client.post("/attachments/nope/complete", json={})).status,
            (await client.get("/attachments/nope")).status,
        )

    assert asyncio.run(_with_client(state, scenario)) == (404, 404, 404, 404)
    state.store.close()


def test_attachment_removed_blob_serves_410(tmp_path):
    from chat_cli import attachments as attachments_store

    state, _ = _service_state(tmp_path)

    async def scenario(client):
        attachment_id, _ = await _upload_via_routes(client, b"abcd")
        attachments_store.remove_blob(state.attachments_root, attachment_id)
        resp = await client.get(f"/attachments/{attachment_id}")
        return resp.status, await resp.json()

    status, body = asyncio.run(_with_client(state, scenario))

    assert status == 410
    assert "error" in body
    state.store.close()


def test_attachment_get_supports_range(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        attachment_id, _ = await _upload_via_routes(client, b"abcdefgh")
        resp = await client.get(f"/attachments/{attachment_id}", headers={"Range": "bytes=2-5"})
        return resp.status, await resp.read()

    status, body = asyncio.run(_with_client(state, scenario))

    assert status == 206
    assert body == b"cdef"
    state.store.close()


def test_attachment_download_query_flips_disposition(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        attachment_id, _ = await _upload_via_routes(client, b"abcd")
        resp = await client.get(f"/attachments/{attachment_id}?download=1")
        return resp.headers["Content-Disposition"]

    disposition = asyncio.run(_with_client(state, scenario))

    assert disposition == "attachment; filename=\"photo.jpg\"; filename*=UTF-8''photo.jpg"
    state.store.close()


def test_attachment_unicode_filename_gets_rfc5987_disposition(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        attachment_id, _ = await _upload_via_routes(client, b"pdf", name="rapport été.pdf", mime="application/pdf")
        resp = await client.get(f"/attachments/{attachment_id}")
        return resp.headers["Content-Disposition"]

    disposition = asyncio.run(_with_client(state, scenario))

    assert 'filename="rapport t.pdf"' in disposition  # ascii fallback
    assert "filename*=UTF-8''rapport%20%C3%A9t%C3%A9.pdf" in disposition
    state.store.close()


def test_attachment_non_media_mime_is_never_served_inline(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        attachment_id, _ = await _upload_via_routes(client, b"<script>alert(1)</script>", name="page.html", mime="text/html")
        resp = await client.get(f"/attachments/{attachment_id}")
        return resp.headers["Content-Type"], resp.headers["Content-Disposition"]

    content_type, disposition = asyncio.run(_with_client(state, scenario))

    assert content_type == "application/octet-stream"
    assert disposition.startswith("attachment; ")
    state.store.close()


def test_message_text_over_the_cap_is_rejected(tmp_path):
    state, _ = _service_state(tmp_path)

    status, body = _post(state, {"text": "x" * (64 * 1024 + 1)})

    assert status == 400
    assert "error" in body
    assert state.store.page()[0] == []
    state.store.close()


# --- attachments on message intake ---


def _message_with_attachment(state, tmp_path, *, text="look at this", extra_body=None):
    async def scenario(client):
        attachment_id, _ = await _upload_via_routes(client, b"fakejpegbytes")
        body = {"text": text, "attachments": [attachment_id]}
        if extra_body:
            body.update(extra_body)
        resp = await client.post("/message", json=body)
        return attachment_id, resp.status, await resp.json()

    return asyncio.run(_with_client(state, scenario))


def test_message_with_attachment_persists_metadata_and_echoes(tmp_path):
    state, _ = _service_state(tmp_path)
    queue = _subscribe(state)

    attachment_id, status, body = _message_with_attachment(state, tmp_path)

    assert status == 200 and body["ok"] is True
    events, _ = state.store.page()
    stored = events[0]
    assert stored["type"] == "user" and stored["text"] == "look at this"
    assert [a["id"] for a in stored["attachments"]] == [attachment_id]
    assert stored["attachments"][0]["name"] == "photo.jpg"
    assert stored["attachments"][0]["mime"] == "image/jpeg"
    assert stored["attachments"][0]["size"] == len(b"fakejpegbytes")
    echoed = _drain(queue)[-1]
    assert [a["id"] for a in echoed["attachments"]] == [attachment_id]
    state.store.close()


def test_attachment_only_message_is_accepted(tmp_path):
    state, _ = _service_state(tmp_path)

    _, status, _ = _message_with_attachment(state, tmp_path, text="")

    assert status == 200
    events, _ = state.store.page()
    assert events[0]["text"] == ""
    assert len(events[0]["attachments"]) == 1
    state.store.close()


def test_message_with_unknown_attachment_id_persists_nothing(tmp_path):
    state, notif_dir = _service_state(tmp_path)
    queue = _subscribe(state)

    async def scenario(client):
        resp = await client.post("/message", json={"text": "hi", "attachments": ["deadbeef"]})
        return resp.status, await resp.json()

    status, body = asyncio.run(_with_client(state, scenario))

    assert status == 400
    assert "deadbeef" in body["error"]
    assert state.store.page()[0] == []
    assert _drain(queue) == []
    assert not notif_dir.exists()
    state.store.close()


def test_message_with_unfinalized_attachment_is_rejected(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        created = await client.post("/attachments", json={"name": "a.bin", "mime": "application/octet-stream", "size": 4})
        attachment_id = (await created.json())["id"]
        resp = await client.post("/message", json={"text": "hi", "attachments": [attachment_id]})
        return resp.status

    assert asyncio.run(_with_client(state, scenario)) == 400
    state.store.close()


def test_notification_carries_attachment_line_with_paths(tmp_path):
    state, notif_dir = _service_state(tmp_path)

    attachment_id, _, _ = _message_with_attachment(state, tmp_path)

    notif = json.loads(next(iter(notif_dir.glob("*-chat-message.json"))).read_text())
    assert notif["message"] == "look at this"
    line = notif["attachments"]
    assert line.startswith("photo.jpg (image/jpeg, 13 B) at ")
    assert str(state.attachments_root / attachment_id / "photo.jpg") in line
    state.store.close()


def test_too_many_attachments_are_rejected(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        resp = await client.post("/message", json={"text": "hi", "attachments": ["x"] * 11})
        return resp.status

    assert asyncio.run(_with_client(state, scenario)) == 400
    state.store.close()


def test_message_without_text_or_attachments_is_rejected(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        resp = await client.post("/message", json={"text": "", "attachments": []})
        return resp.status

    assert asyncio.run(_with_client(state, scenario)) == 400
    state.store.close()


def test_attachment_create_rejects_header_hostile_mime(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        evil = await client.post("/attachments", json={"name": "a.png", "mime": "image/png\r\nX-Evil: 1", "size": 4})
        slashless = await client.post("/attachments", json={"name": "a.bin", "mime": "notamime", "size": 4})
        return evil.status, slashless.status

    assert asyncio.run(_with_client(state, scenario)) == (400, 400)
    state.store.close()


def test_attachment_traversal_id_is_a_plain_404(tmp_path):
    state, _ = _service_state(tmp_path)

    async def scenario(client):
        return (
            (await client.get("/attachments/..%2F..%2Fetc")).status,
            (await client.get("/attachments/deadbeef/status")).status,
            (await client.post("/attachments/deadbeef/complete", json={})).status,
        )

    assert asyncio.run(_with_client(state, scenario)) == (404, 404, 404)
    state.store.close()
