"""Tests for the node client: every call against the in-process fake node, the two refusals and the
error mapping, the chunked resumable upload, the blob download, the live socket, and the env read that
decides whether the daemon has a node at all."""

import asyncio

import aiohttp
import pytest
from chat_cli import node_client
from chat_cli.node_client import BurstRefusedError, NodeClient, NodeError, SpeakingRefusedError, new_session, node_config_from_env

from .fake_node import BURST_REFUSAL, SPEAKING_REFUSAL, FakeNode, connected_client, running_node

FULL_ENV = {"AGENT_NAME": "vesta", "AGENT_TOKEN": "secret", "BOX_HOST": "10.0.0.4", "VESTAD_PORT": "8443"}
PHOTO = {"id": "abc", "name": "p.png", "mime": "image/png", "size": 3, "width": 4}


def run(fake, scenario):
    """Drive one scenario against a running fake, on the session the daemon would use."""

    async def main():
        async with connected_client(fake) as client:
            return await scenario(client)

    return asyncio.run(main())


def run_with_token(fake, token, scenario):
    """The same, with a token of the caller's choosing, so the gate can refuse it."""

    async def main():
        async with running_node(fake) as base_url:
            config = {"base_url": base_url, "token": token, "agent": fake.agent}
            session = new_session(config)
            try:
                return await scenario(NodeClient(config, session))
            finally:
                await session.close()

    return asyncio.run(main())


def paths(fake, method):
    return [path for verb, path, _ in fake.requests if verb == method]


def test_rooms_lists_every_room_the_node_has_this_agent_in():
    fake = FakeNode()
    fake.seed_room(["vesta"])
    fake.seed_room(["vesta", "bob"])
    fake.seed_room(["bob"])

    rooms = run(fake, lambda client: client.rooms())

    assert [room["id"] for room in rooms] == ["dm:vesta", "dm:bob:vesta"]
    assert rooms[1]["agents"] == ["bob", "vesta"]
    assert rooms[0]["name"] is None


def test_open_room_creates_once_and_answers_the_same_room_again():
    fake = FakeNode()

    async def scenario(client):
        return await client.open_room(["vesta", "bob"], None), await client.open_room(["bob", "vesta"], None)

    first, second = run(fake, scenario)

    assert first["id"] == "dm:bob:vesta"
    assert second == first
    assert len(fake.rooms) == 1


def test_open_room_mints_a_fresh_group_for_every_named_open():
    fake = FakeNode()

    async def scenario(client):
        return await client.open_room(["vesta", "bob"], "trip planning"), await client.open_room(["vesta", "bob"], "trip planning")

    first, second = run(fake, scenario)

    assert first["name"] == "trip planning"
    assert first["id"].startswith("grp-")
    assert second["id"] != first["id"]
    assert len(fake.rooms) == 2


def test_history_after_reads_a_page_and_the_id_to_continue_from():
    fake = FakeNode()
    fake.seed_room(["vesta"])
    for text in ("one", "two", "three"):
        fake.seed_message("dm:vesta", "user", "user", text)

    async def scenario(client):
        first, cursor = await client.history_after("dm:vesta", 0, 2)
        rest, done = await client.history_after("dm:vesta", cursor, 2)
        return first, cursor, rest, done

    first, cursor, rest, done = run(fake, scenario)

    assert [message["text"] for message in first] == ["one", "two"]
    assert cursor == 2
    assert [message["text"] for message in rest] == ["three"]
    assert done is None
    assert "after=2" in paths(fake, "GET")[1]


def test_history_reads_every_optional_field_the_message_wire_carries():
    fake = FakeNode()
    fake.seed_room(["vesta"])
    stored = fake.seed_message("dm:vesta", "chat", "vesta", "hi")
    stored["origin_id"] = 12
    stored["input_method"] = "voice"
    stored["intent_id"] = "c-9"
    stored["attachments"] = [PHOTO]

    events, _ = run(fake, lambda client: client.history_after("dm:vesta", 0, 10))

    assert events[0]["origin_id"] == 12
    assert events[0]["input_method"] == "voice"
    assert events[0]["intent_id"] == "c-9"
    assert events[0]["attachments"] == [PHOTO]


def test_post_answers_the_node_id_and_lands_the_message():
    fake = FakeNode()
    fake.seed_room(["vesta"])

    node_id = run(fake, lambda client: client.post("dm:vesta", "on it", []))

    assert node_id == 1
    assert fake.messages[0]["sender"] == "vesta"
    assert fake.messages[0]["text"] == "on it"


def test_post_refused_while_the_user_is_talking():
    fake = FakeNode()
    fake.seed_room(["vesta"])
    fake.refuse_speaking = True

    with pytest.raises(SpeakingRefusedError) as refusal:
        run(fake, lambda client: client.post("dm:vesta", "hold on", []))

    assert str(refusal.value) == SPEAKING_REFUSAL


def test_post_refused_by_the_burst_guard():
    fake = FakeNode()
    fake.seed_room(["vesta"])
    fake.refuse_burst = True

    with pytest.raises(BurstRefusedError) as refusal:
        run(fake, lambda client: client.post("dm:vesta", "again", []))

    assert str(refusal.value) == BURST_REFUSAL


def test_a_room_the_node_does_not_hold_is_a_node_error_carrying_the_reason():
    fake = FakeNode()

    with pytest.raises(NodeError) as failure:
        run(fake, lambda client: client.post("dm:nobody", "hi", []))

    assert "no such room" in str(failure.value)


def test_a_wrong_token_is_a_node_error():
    fake = FakeNode(token="the-real-one")

    with pytest.raises(NodeError) as failure:
        run_with_token(fake, "wrong", lambda client: client.rooms())

    assert "unauthorized" in str(failure.value)


def test_an_unreachable_node_is_a_node_error():
    config = {"base_url": "http://127.0.0.1:1", "token": "t", "agent": "vesta"}

    async def main():
        session = new_session(config)
        try:
            await NodeClient(config, session).rooms()
        finally:
            await session.close()

    with pytest.raises(NodeError):
        asyncio.run(main())


def test_import_messages_counts_what_landed_and_what_was_already_there():
    fake = FakeNode()
    fake.seed_room(["vesta"])
    items = [
        {"origin_id": 1, "ts": "2026-09-05T10:00:00.000Z", "type": "user", "text": "old"},
        {"origin_id": 2, "ts": "2026-09-05T10:00:01.000Z", "type": "chat", "text": "reply"},
    ]

    async def scenario(client):
        return await client.import_messages("dm:vesta", items), await client.import_messages("dm:vesta", items)

    first, again = run(fake, scenario)

    assert first == {"imported": 2, "skipped": 0}
    assert again == {"imported": 0, "skipped": 2}
    assert [message["sender"] for message in fake.messages] == ["user", "vesta"]
    assert [message["origin_id"] for message in fake.messages] == [1, 2]


def test_an_unreadable_stamp_refuses_the_whole_batch():
    fake = FakeNode()
    fake.seed_room(["vesta"])
    items = [{"origin_id": 7, "ts": "yesterday", "type": "user", "text": "old"}]

    with pytest.raises(NodeError) as failure:
        run(fake, lambda client: client.import_messages("dm:vesta", items))

    assert "invalid ts on origin_id 7" in str(failure.value)
    assert fake.messages == []


def test_peers_lists_the_other_agents():
    fake = FakeNode()
    fake.peers = ["bob", "cy"]

    assert run(fake, lambda client: client.peers()) == ["bob", "cy"]
    assert paths(fake, "GET") == ["/agents/vesta/peers"]


def test_upload_opens_a_session_sends_every_chunk_in_order_then_completes(tmp_path, monkeypatch):
    monkeypatch.setattr(node_client, "UPLOAD_CHUNK_BYTES", 8)
    fake = FakeNode()
    blob = tmp_path / "clip.bin"
    blob.write_bytes(b"0123456789abcdefghij")

    meta = run(fake, lambda client: client.upload(blob, "application/octet-stream"))

    assert meta["name"] == "clip.bin"
    assert meta["mime"] == "application/octet-stream"
    assert meta["size"] == 20
    assert bytes(fake.attachments[meta["id"]].data) == b"0123456789abcdefghij"
    assert fake.attachments[meta["id"]].finalized is True
    assert [path.split("offset=")[1] for path in paths(fake, "PUT")] == ["0", "8", "16"]
    assert paths(fake, "POST") == ["/rooms/attachments", f"/rooms/attachments/{meta['id']}/complete"]


def test_upload_declares_the_media_facts_it_is_given(tmp_path):
    fake = FakeNode()
    blob = tmp_path / "shot.png"
    blob.write_bytes(b"\x89PNG")

    meta = run(fake, lambda client: client.upload(blob, "image/png", {"width": 800, "height": 600}))

    created = next(body for method, path, body in fake.requests if method == "POST" and path == "/rooms/attachments")
    assert created == {"name": "shot.png", "mime": "image/png", "size": 4, "width": 800, "height": 600}
    assert meta["width"] == 800
    assert meta["height"] == 600


def test_an_empty_file_uploads_with_no_chunk_at_all(tmp_path):
    fake = FakeNode()
    blob = tmp_path / "empty.txt"
    blob.write_bytes(b"")

    meta = run(fake, lambda client: client.upload(blob, "text/plain"))

    assert meta["size"] == 0
    assert paths(fake, "PUT") == []
    assert fake.attachments[meta["id"]].finalized is True


def test_upload_re_sends_from_the_staged_size_a_conflict_names(tmp_path, monkeypatch):
    monkeypatch.setattr(node_client, "UPLOAD_CHUNK_BYTES", 8)
    fake = FakeNode()
    fake.rewind_stage_to = 4
    blob = tmp_path / "clip.bin"
    blob.write_bytes(b"0123456789abcdefghij")

    meta = run(fake, lambda client: client.upload(blob, "application/octet-stream"))

    assert bytes(fake.attachments[meta["id"]].data) == b"0123456789abcdefghij"
    assert [path.split("offset=")[1] for path in paths(fake, "PUT")] == ["0", "8", "4", "12"]


def test_a_node_that_stages_nothing_ends_the_upload_instead_of_spinning(tmp_path, monkeypatch):
    monkeypatch.setattr(node_client, "UPLOAD_CHUNK_BYTES", 8)
    fake = FakeNode()
    fake.stall_chunks = True
    blob = tmp_path / "clip.bin"
    blob.write_bytes(b"0123456789abcdefghij")

    async def scenario(client):
        return await asyncio.wait_for(client.upload(blob, "application/octet-stream"), timeout=5)

    with pytest.raises(NodeError) as failure:
        run(fake, scenario)

    assert "no progress at offset 0" in str(failure.value)


def test_upload_asks_for_the_staged_size_when_a_chunk_response_is_lost(tmp_path, monkeypatch):
    monkeypatch.setattr(node_client, "UPLOAD_CHUNK_BYTES", 8)
    fake = FakeNode()
    fake.drop_answers_at = 0
    blob = tmp_path / "clip.bin"
    blob.write_bytes(b"0123456789abcdefghij")

    meta = run(fake, lambda client: client.upload(blob, "application/octet-stream"))

    assert bytes(fake.attachments[meta["id"]].data) == b"0123456789abcdefghij"
    assert f"/rooms/attachments/{meta['id']}/status" in paths(fake, "GET")


def test_download_writes_the_blob_into_a_directory_it_creates(tmp_path):
    fake = FakeNode()
    source = tmp_path / "photo.png"
    source.write_bytes(b"\x89PNG payload")
    dest = tmp_path / "store" / "an-id" / "photo.png"

    async def scenario(client):
        meta = await client.upload(source, "image/png")
        await client.download(meta["id"], dest)

    run(fake, scenario)

    assert dest.read_bytes() == b"\x89PNG payload"


def test_download_of_a_blob_the_node_does_not_hold_is_a_node_error(tmp_path):
    fake = FakeNode()

    with pytest.raises(NodeError):
        run(fake, lambda client: client.download("0" * 32, tmp_path / "x.bin"))


def test_the_socket_carries_the_token_and_reads_the_live_edge():
    fake = FakeNode()

    async def scenario(client):
        async with client.ws_connect() as socket:
            await fake.emit({"type": "room_created", "room": {"id": "dm:vesta", "name": None, "agents": ["vesta"]}})
            return await socket.receive_json()

    assert run(fake, scenario)["type"] == "room_created"


def test_the_socket_is_refused_without_the_right_token():
    fake = FakeNode(token="the-real-one")

    async def scenario(client):
        async with client.ws_connect() as socket:
            return socket.closed

    with pytest.raises(aiohttp.WSServerHandshakeError):
        run_with_token(fake, "wrong", scenario)


def test_node_config_from_env_needs_all_four_values():
    assert node_config_from_env(FULL_ENV) == {"base_url": "https://10.0.0.4:8443", "token": "secret", "agent": "vesta"}
    for key in FULL_ENV:
        missing = {name: value for name, value in FULL_ENV.items() if name != key}
        assert node_config_from_env(missing) is None
        assert node_config_from_env({**FULL_ENV, key: ""}) is None


def test_an_https_node_is_dialed_with_no_certificate_check():
    async def main():
        secure = new_session({"base_url": "https://box:8443", "token": "t", "agent": "vesta"})
        plain = new_session({"base_url": "http://127.0.0.1:9", "token": "t", "agent": "vesta"})
        try:
            return secure.connector._ssl, plain.connector._ssl
        finally:
            await secure.close()
            await plain.close()

    assert asyncio.run(main()) == (False, True)
