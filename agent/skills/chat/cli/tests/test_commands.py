"""Tests for the verbs that call the node directly: `chat rooms`, `chat rooms create`, `chat peers`,
and `chat import-to-node`. Each drives the real command function against the fake node, which is served
from its own loop in a background thread, since the commands own their `asyncio.run`."""

import argparse
import asyncio
import contextlib
import json
import threading

import pytest
from aiohttp.test_utils import TestServer
from chat_cli import attachments, commands
from chat_cli.node_client import NODE_UNREACHABLE
from chat_cli.store import Store, direct_room_id, store_path

from .fake_node import FakeNode

AGENT = "vesta"
DIRECT = direct_room_id(AGENT)


@contextlib.contextmanager
def serving(fake, monkeypatch):
    """Serve the fake from a background loop and point the commands at it, so a command's own
    `asyncio.run` drives the client while the server answers from the other thread."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    server = TestServer(fake.app)
    asyncio.run_coroutine_threadsafe(server.start_server(), loop).result(timeout=10)
    base_url = str(server.make_url("")).rstrip("/")
    monkeypatch.setattr(commands, "_node_config", lambda: {"base_url": base_url, "token": fake.token, "agent": fake.agent})
    try:
        yield
    finally:
        asyncio.run_coroutine_threadsafe(server.close(), loop).result(timeout=10)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=10)
        loop.close()


def _imports(fake):
    """Every import request body the fake was handed, in order."""
    return [payload for method, path, payload in fake.requests if path == f"/rooms/{DIRECT}/messages/import"]


def _args(tmp_path, **overrides):
    defaults = {"data_dir": str(tmp_path), "json": False, "name": None, "agents": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_rooms_prints_one_line_per_room(tmp_path, monkeypatch, capsys):
    fake = FakeNode()
    fake.seed_room([AGENT])
    group = fake.seed_room([AGENT, "bob"], name="standup")

    with serving(fake, monkeypatch):
        commands.cmd_rooms(_args(tmp_path))

    assert capsys.readouterr().out.splitlines() == [f"{DIRECT}  vesta", f"{group.id}  standup"]


def test_rooms_json_prints_the_raw_list(tmp_path, monkeypatch, capsys):
    fake = FakeNode()
    fake.seed_room([AGENT, "bob"])

    with serving(fake, monkeypatch):
        commands.cmd_rooms(_args(tmp_path, json=True))

    assert json.loads(capsys.readouterr().out) == [{"id": "dm:bob:vesta", "name": None, "agents": ["bob", "vesta"]}]


def test_rooms_create_opens_the_room_and_prints_it(tmp_path, monkeypatch, capsys):
    fake = FakeNode()

    with serving(fake, monkeypatch):
        commands.cmd_rooms_create(_args(tmp_path, name="planning", agents="bob,cleo"))

    room = json.loads(capsys.readouterr().out)
    assert room["name"] == "planning"
    assert room["agents"] == ["bob", "cleo", "vesta"]
    assert fake.rooms[room["id"]].name == "planning"


def test_peers_prints_one_name_per_line(tmp_path, monkeypatch, capsys):
    fake = FakeNode()
    fake.peers = ["bob", "cleo"]

    with serving(fake, monkeypatch):
        commands.cmd_peers(_args(tmp_path))
        plain = capsys.readouterr().out
        commands.cmd_peers(_args(tmp_path, json=True))

    assert plain.splitlines() == ["bob", "cleo"]
    assert json.loads(capsys.readouterr().out) == ["bob", "cleo"]


def test_import_to_node_hands_over_every_unsynced_row_with_its_origin_id(tmp_path, monkeypatch, capsys):
    fake = FakeNode()
    fake.seed_room([AGENT])
    store = Store(store_path(tmp_path), AGENT)
    store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "hello", "input_method": "typed"})
    store.append({"type": "chat", "ts": "2026-01-01T00:00:01", "text": "hi back"})
    store.append({"type": "chat", "ts": "2026-01-01T00:00:02", "text": "already there", "node_id": 7})
    store.close()

    with serving(fake, monkeypatch):
        commands.cmd_import_to_node(_args(tmp_path))

    assert json.loads(capsys.readouterr().out) == {"status": "imported", "imported": 2, "skipped": 0}
    body = _imports(fake)[0]
    assert [(item["origin_id"], item["type"], item["text"]) for item in body["messages"]] == [(1, "user", "hello"), (2, "chat", "hi back")]
    assert body["messages"][0]["input_method"] == "typed"


def test_import_to_node_is_re_runnable_and_reports_what_the_node_skipped(tmp_path, monkeypatch, capsys):
    fake = FakeNode()
    fake.seed_room([AGENT])
    store = Store(store_path(tmp_path), AGENT)
    store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "hello"})
    store.close()

    with serving(fake, monkeypatch):
        commands.cmd_import_to_node(_args(tmp_path))
        capsys.readouterr()
        commands.cmd_import_to_node(_args(tmp_path))

    assert json.loads(capsys.readouterr().out) == {"status": "imported", "imported": 0, "skipped": 1}


def test_import_to_node_sends_one_request_per_batch(tmp_path, monkeypatch, capsys):
    fake = FakeNode()
    fake.seed_room([AGENT])
    store = Store(store_path(tmp_path), AGENT)
    for index in range(5):
        store.append({"type": "user", "ts": f"2026-01-01T00:00:0{index}", "text": f"line {index}"})
    store.close()
    monkeypatch.setattr(commands, "IMPORT_BATCH_SIZE", 2)

    with serving(fake, monkeypatch):
        commands.cmd_import_to_node(_args(tmp_path))

    batches = _imports(fake)
    assert [len(batch["messages"]) for batch in batches] == [2, 2, 1]
    assert json.loads(capsys.readouterr().out) == {"status": "imported", "imported": 5, "skipped": 0}


def test_import_to_node_uploads_an_attachment_and_skips_one_whose_file_is_gone(tmp_path, monkeypatch, capsys):
    fake = FakeNode()
    fake.seed_room([AGENT])
    root = attachments.attachments_root(tmp_path)
    source = tmp_path / "chart.png"
    source.write_bytes(b"pngbytes")
    kept = attachments.ingest_file(root, source, "image/png")
    gone = attachments.ingest_file(root, source, "image/png")
    attachments.remove_blob(root, gone["id"])
    store = Store(store_path(tmp_path), AGENT)
    store.append({"type": "chat", "ts": "2026-01-01T00:00:00", "text": "here", "attachments": [kept, gone]})
    store.close()

    with serving(fake, monkeypatch):
        commands.cmd_import_to_node(_args(tmp_path))

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": "imported", "imported": 1, "skipped": 0}
    assert gone["id"] in captured.err
    [upload] = list(fake.attachments.values())
    assert bytes(upload.data) == b"pngbytes" and upload.finalized
    body = _imports(fake)[0]
    assert body["messages"][0]["attachments"] == [upload.meta["id"]]


def test_a_node_failure_is_one_json_line_on_stderr(tmp_path, monkeypatch, capsys):
    fake = FakeNode()  # nothing seeded, so the import is a 404

    store = Store(store_path(tmp_path), AGENT)
    store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "hello"})
    store.close()

    with serving(fake, monkeypatch), pytest.raises(SystemExit) as exit_code:
        commands.cmd_import_to_node(_args(tmp_path))

    captured = capsys.readouterr()
    assert exit_code.value.code == 1
    assert captured.out == ""
    assert "error" in json.loads(captured.err)


def test_a_verb_without_a_node_in_the_environment_names_what_it_needs(tmp_path, monkeypatch, capsys):
    for key in ("AGENT_NAME", "AGENT_TOKEN", "BOX_HOST", "VESTAD_PORT"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(SystemExit):
        commands.cmd_peers(_args(tmp_path))

    assert json.loads(capsys.readouterr().err) == {"error": NODE_UNREACHABLE}
