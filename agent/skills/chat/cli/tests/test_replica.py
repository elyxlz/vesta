"""Tests for the replica loop: the catch-up pull that walks every page, the live socket's messages and
room events, the attachment each replicated message brings down with it, the notification a message
that is not this agent's own becomes, and the reconnect that resumes from the last node id."""

import asyncio
import contextlib
import json
import uuid

from chat_cli import replica
from chat_cli.replica import ReplicaState, catch_up, ingest_message, run_replica
from chat_cli.store import Store, direct_room_id, store_path

from .fake_node import FakeNode, FakeUpload, connected_client

AGENT = "vesta"
DIRECT = direct_room_id(AGENT)


@contextlib.asynccontextmanager
async def replica_state(fake, tmp_path):
    """A replica wired to the running fake, over the store and the dirs a daemon would hand it."""
    async with connected_client(fake) as client:
        store = Store(store_path(tmp_path / "data"), fake.agent)
        try:
            yield ReplicaState(
                store=store,
                client=client,
                attachments_root=tmp_path / "attachments",
                notifications_dir=tmp_path / "notifications",
                agent=fake.agent,
                echo=lambda event: None,
            )
        finally:
            store.close()


def run(fake, tmp_path, scenario):
    """One scenario against a replica state, with no loop running: the ingest paths drive directly."""

    async def main():
        async with replica_state(fake, tmp_path) as state:
            return await scenario(state)

    return asyncio.run(main())


def run_live(fake, tmp_path, scenario):
    """The same, with `run_replica` running against the fake, so the socket is the live edge."""

    async def main():
        async with replica_state(fake, tmp_path) as state:
            shutdown = asyncio.Event()
            task = asyncio.create_task(run_replica(state, shutdown))
            try:
                await wait_for(lambda: state.connected)
                return await scenario(state)
            finally:
                shutdown.set()
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    return asyncio.run(main())


async def wait_for(predicate) -> None:
    """Poll a condition to a bounded deadline: the loop persists and notifies from worker threads, so
    an assertion waits for the effect instead of sleeping a guessed amount."""
    for _ in range(1000):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not met before the deadline")


def seed_attachment(fake, name="photo.jpg", mime="image/jpeg", data=b"hello world!"):
    meta = {"id": uuid.uuid4().hex, "name": name, "mime": mime, "size": len(data)}
    fake.attachments[meta["id"]] = FakeUpload(meta=meta, data=bytearray(data), finalized=True)
    return meta


def texts(state, room=DIRECT):
    events, _ = state.store.page(room=room)
    return [event["text"] for event in events]


def notifications_of(state, type_="message"):
    directory = state.notifications_dir
    paths = sorted(directory.glob(f"*-chat-{type_}.json")) if directory.exists() else []
    return [json.loads(path.read_text()) for path in paths]


def paths_of(fake, method="GET"):
    return [path for verb, path, _ in fake.requests if verb == method]


def test_catch_up_walks_every_page_and_persists_in_order(tmp_path, monkeypatch):
    monkeypatch.setattr(replica, "REPLICA_PAGE_SIZE", 2)
    fake = FakeNode()
    fake.seed_room([AGENT])
    for text in ("one", "two", "three"):
        fake.seed_message(DIRECT, "user", "user", text)

    def scenario(state):
        async def main():
            ingested = await catch_up(state)
            assert texts(state) == ["one", "two", "three"]
            return ingested

        return main()

    assert run(fake, tmp_path, scenario) == 3
    assert paths_of(fake).count(f"/rooms/{DIRECT}/history?after=0&limit=2") == 1
    assert f"/rooms/{DIRECT}/history?after=2&limit=2" in paths_of(fake)


def test_catch_up_stores_every_room_the_node_has_this_agent_in(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])
    group = fake.seed_room([AGENT, "bob"], name="planning")

    def scenario(state):
        async def main():
            await catch_up(state)
            return state.store.rooms()

        return main()

    assert run(fake, tmp_path, scenario) == sorted(
        [{"id": DIRECT, "name": None, "agents": [AGENT]}, {"id": group.id, "name": "planning", "agents": ["bob", "vesta"]}],
        key=lambda room: room["id"],
    )


def test_a_message_already_stored_is_not_persisted_twice(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])
    message = fake.seed_message(DIRECT, "user", "user", "hello")

    def scenario(state):
        async def main():
            first = await ingest_message(state, message)
            second = await ingest_message(state, message)
            return first, second, texts(state)

        return main()

    assert run(fake, tmp_path, scenario) == (True, False, ["hello"])


def test_an_imported_message_stamps_the_local_row_it_came_from(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])

    def scenario(state):
        async def main():
            local_id = state.store.append({"type": "chat", "ts": "2026-09-05T09:00:00+00:00", "text": "already here"})
            message = fake.seed_message(DIRECT, "chat", AGENT, "already here", origin_id=local_id)
            ingested = await ingest_message(state, message)
            return ingested, texts(state), state.store.max_node_id(DIRECT)

        return main()

    assert run(fake, tmp_path, scenario) == (False, ["already here"], 1)


def test_an_origin_frame_naming_a_replicated_row_lands_as_its_own_message(tmp_path):
    """A restored store can hold a replicated row under a local id a later origin id also names. That
    row carries a node id, so the frame is persisted as the message it is."""
    fake = FakeNode()
    fake.seed_room([AGENT])

    def scenario(state):
        async def main():
            local_id = state.store.append({"type": "chat", "ts": "2026-09-05T09:00:00+00:00", "text": "replicated", "node_id": 40})
            message = fake.seed_message(DIRECT, "chat", AGENT, "imported", origin_id=local_id)
            ingested = await ingest_message(state, message)
            return ingested, texts(state)

        return main()

    assert run(fake, tmp_path, scenario) == (True, ["replicated", "imported"])


def test_a_live_user_message_persists_and_becomes_a_notification(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])

    def scenario(state):
        async def main():
            message = fake.seed_message(DIRECT, "user", "user", "are you there")
            await fake.emit(message)
            await wait_for(lambda: notifications_of(state))
            return texts(state), notifications_of(state)

        return main()

    stored, written = run_live(fake, tmp_path, scenario)
    assert stored == ["are you there"]
    assert len(written) == 1
    assert written[0]["sender"] == "user"
    assert written[0]["room"] == DIRECT
    assert written[0]["interrupt"] is True
    assert written[0]["reply_command"] == "chat send --message -"


def test_this_agents_own_message_persists_without_a_notification(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])

    def scenario(state):
        async def main():
            message = fake.seed_message(DIRECT, "chat", AGENT, "on my way")
            await fake.emit(message)
            await wait_for(lambda: texts(state) == ["on my way"])
            return notifications_of(state)

        return main()

    assert run_live(fake, tmp_path, scenario) == []


def test_this_agents_own_message_reaches_the_old_services_subscribers(tmp_path):
    # The daemon's send posts and nothing more, so the reply's live echo to today's clients is written
    # here, where the row itself lands.
    fake = FakeNode()
    fake.seed_room([AGENT])
    echoed = []

    def scenario(state):
        async def main():
            state.echo = echoed.append
            await fake.emit(fake.seed_message(DIRECT, "chat", AGENT, "on my way"))
            await wait_for(lambda: len(echoed) == 1)
            await fake.emit(fake.seed_message(DIRECT, "user", "user", "thanks"))
            await wait_for(lambda: texts(state) == ["on my way", "thanks"])
            return echoed

        return main()

    assert [(event["text"], event["node_id"], event["sender"]) for event in run_live(fake, tmp_path, scenario)] == [("on my way", 1, AGENT)]


def test_a_peers_message_in_a_group_waits_for_idle(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])
    room = fake.seed_room([AGENT, "bob"], name="planning")

    def scenario(state):
        async def main():
            message = fake.seed_message(room.id, "chat", "bob", "shipping tonight")
            await fake.emit(message)
            await wait_for(lambda: notifications_of(state))
            return notifications_of(state)[0]

        return main()

    written = run_live(fake, tmp_path, scenario)
    assert written["interrupt"] is False
    assert written["room_name"] == "planning"
    assert written["members"] == "bob, vesta"
    assert written["reply_command"] == f"chat send --room {room.id} --message -"


def test_an_attachment_lands_in_the_local_store_and_the_notification_names_its_path(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])
    meta = seed_attachment(fake)

    def scenario(state):
        async def main():
            message = fake.seed_message(DIRECT, "user", "user", "look at this", attachments=[meta])
            await fake.emit(message)
            await wait_for(lambda: notifications_of(state))
            return notifications_of(state)[0]

        return main()

    written = run_live(fake, tmp_path, scenario)
    blob = tmp_path / "attachments" / meta["id"] / "photo.jpg"
    assert blob.read_bytes() == b"hello world!"
    assert json.loads((blob.parent / ".meta.json").read_text())["mime"] == "image/jpeg"
    assert written["attachments"] == f"photo.jpg (image/jpeg, 12 B) at {blob}"


def test_an_attachment_is_stored_under_a_safe_name_and_the_notification_names_that_file(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])
    meta = seed_attachment(fake, name="../.hidden/report.pdf", mime="application/pdf", data=b"pdf")

    def scenario(state):
        async def main():
            await fake.emit(fake.seed_message(DIRECT, "user", "user", "read this", attachments=[meta]))
            await wait_for(lambda: notifications_of(state))
            return notifications_of(state)[0]

        return main()

    written = run_live(fake, tmp_path, scenario)
    blob = tmp_path / "attachments" / meta["id"] / "report.pdf"
    assert blob.read_bytes() == b"pdf"
    assert written["attachments"] == f"report.pdf (application/pdf, 3 B) at {blob}"


def test_an_attachment_the_node_will_not_serve_stays_on_the_message(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])
    meta = seed_attachment(fake)
    fake.refuse_downloads = True

    def scenario(state):
        async def main():
            await fake.emit(fake.seed_message(DIRECT, "user", "user", "look at this", attachments=[meta]))
            await wait_for(lambda: notifications_of(state))
            events, _ = state.store.page(room=DIRECT)
            return events[0], notifications_of(state)[0]

        return main()

    event, written = run_live(fake, tmp_path, scenario)
    assert [one["id"] for one in event["attachments"]] == [meta["id"]]
    assert written["attachments"] == "photo.jpg (image/jpeg, 12 B) could not be fetched from the node"


def test_an_unreadable_attachment_id_leaves_the_loop_running(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])
    broken = {"id": "not-hex", "name": "photo.jpg", "mime": "image/jpeg", "size": 3}

    def scenario(state):
        async def main():
            await fake.emit(fake.seed_message(DIRECT, "user", "user", "look at this", attachments=[broken]))
            await wait_for(lambda: notifications_of(state))
            await fake.emit(fake.seed_message(DIRECT, "user", "user", "and this"))
            await wait_for(lambda: len(notifications_of(state)) == 2)
            events, _ = state.store.page(room=DIRECT)
            return [event["text"] for event in events], [one["id"] for one in events[0]["attachments"]], notifications_of(state)[0]

        return main()

    texts_stored, carried, written = run_live(fake, tmp_path, scenario)
    assert texts_stored == ["look at this", "and this"]
    assert carried == ["not-hex"]
    assert "could not be fetched from the node" in written["attachments"]


def test_a_room_created_event_lands_in_the_store_and_a_deletion_removes_it(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])
    group = fake.seed_room([AGENT, "bob"], name="planning")

    def scenario(state):
        async def main():
            await fake.emit({"type": "room_created", "room": group.wire()})
            await wait_for(lambda: state.store.room(group.id) is not None)
            stored = state.store.room(group.id)
            await fake.emit({"type": "room_deleted", "room": group.id})
            await wait_for(lambda: state.store.room(group.id) is None)
            return stored

        return main()

    assert run_live(fake, tmp_path, scenario) == {"id": group.id, "name": "planning", "agents": ["bob", "vesta"]}


def test_the_user_finishing_a_turn_becomes_its_notification(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])

    def scenario(state):
        async def main():
            await fake.emit({"type": "user_finished_talking", "room": DIRECT})
            await wait_for(lambda: notifications_of(state, "user_finished_talking"))
            return notifications_of(state, "user_finished_talking")[0]

        return main()

    assert run_live(fake, tmp_path, scenario)["room"] == DIRECT


def test_a_dropped_socket_reconnects_and_pulls_from_the_last_node_id(tmp_path, monkeypatch):
    monkeypatch.setattr(replica, "REPLICA_RECONNECT_BASE_SECS", 0.01)
    fake = FakeNode()
    fake.seed_room([AGENT])

    def scenario(state):
        async def main():
            message = fake.seed_message(DIRECT, "user", "user", "first")
            await fake.emit(message)
            await wait_for(lambda: texts(state) == ["first"])
            await fake.close_sockets()
            resumed = f"/rooms/{DIRECT}/history?after={message['id']}&limit={replica.REPLICA_PAGE_SIZE}"
            await wait_for(lambda: resumed in paths_of(fake))
            return resumed in paths_of(fake)

        return main()

    assert run_live(fake, tmp_path, scenario) is True
