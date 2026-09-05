"""Tests for `chat attachments list|rm`: the agent's disk-management verbs. Direct disk readers
(store db + attachments dir), no daemon socket, single-line JSON envelopes."""

import argparse
import json

import pytest
from chat_cli import attachments
from chat_cli.commands import cmd_attachments_list, cmd_attachments_rm
from chat_cli.store import Store, store_path


def _seed(tmp_path):
    """Three finalized attachments: a large received one, a small sent one, and an unreferenced one."""
    root = tmp_path / "attachments"
    store = Store(store_path(tmp_path))
    big = attachments.ingest_file(root, _file(tmp_path, "video.mp4", 9000), "video/mp4")
    small = attachments.ingest_file(root, _file(tmp_path, "note.txt", 10), "text/plain")
    orphan = attachments.ingest_file(root, _file(tmp_path, "orphan.bin", 500), None)
    store.append({"type": "user", "ts": "2026-08-01T00:00:00", "text": "look", "attachments": [big]})
    store.append({"type": "chat", "ts": "2026-08-02T00:00:00", "text": "here", "attachments": [small]})
    store.close()
    return root, big, small, orphan


def _file(tmp_path, name, size):
    source = tmp_path / name
    source.write_bytes(b"x" * size)
    return source


def _args(tmp_path, **overrides):
    defaults = {"data_dir": str(tmp_path), "sort": "size", "limit": None, "min_size": None, "ids": []}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _list(tmp_path, capsys, **overrides):
    cmd_attachments_list(_args(tmp_path, **overrides))
    out = capsys.readouterr().out
    assert "\n" not in out.strip()  # single-line envelope
    return json.loads(out)


def test_list_sorts_largest_first_with_totals(tmp_path, capsys):
    _, big, small, orphan = _seed(tmp_path)

    body = _list(tmp_path, capsys)

    assert [a["id"] for a in body["attachments"]] == [big["id"], orphan["id"], small["id"]]
    assert body["count"] == 3
    assert body["total_bytes"] == 9000 + 500 + 10
    listed_big = body["attachments"][0]
    assert listed_big["name"] == "video.mp4"
    assert listed_big["mime"] == "video/mp4"
    assert listed_big["ts"] == "2026-08-01T00:00:00"
    assert listed_big["direction"] == "received"
    assert listed_big["removed"] is False


def test_list_joins_direction_from_the_referencing_event(tmp_path, capsys):
    _, big, small, orphan = _seed(tmp_path)

    body = _list(tmp_path, capsys)
    by_id = {a["id"]: a for a in body["attachments"]}

    assert by_id[big["id"]]["direction"] == "received"
    assert by_id[small["id"]]["direction"] == "sent"
    assert by_id[orphan["id"]]["direction"] is None
    assert by_id[orphan["id"]]["ts"] is None


def test_list_sort_date_limit_and_min_size_filter(tmp_path, capsys):
    _, big, small, orphan = _seed(tmp_path)

    by_date = _list(tmp_path, capsys, sort="date")
    assert [a["id"] for a in by_date["attachments"]][:2] == [small["id"], big["id"]]  # newest first, unreferenced last

    limited = _list(tmp_path, capsys, limit=1)
    assert [a["id"] for a in limited["attachments"]] == [big["id"]]

    sized = _list(tmp_path, capsys, min_size=400)
    assert {a["id"] for a in sized["attachments"]} == {big["id"], orphan["id"]}


def test_removed_attachment_lists_with_flag_and_leaves_total(tmp_path, capsys):
    root, big, _, _ = _seed(tmp_path)
    attachments.remove_blob(root, big["id"])

    body = _list(tmp_path, capsys)
    by_id = {a["id"]: a for a in body["attachments"]}

    assert by_id[big["id"]]["removed"] is True
    assert body["total_bytes"] == 500 + 10  # removed bytes are freed, so they leave the total


def test_rm_frees_bytes_keeps_meta_and_is_idempotent(tmp_path, capsys):
    root, big, _, _ = _seed(tmp_path)

    cmd_attachments_rm(_args(tmp_path, ids=[big["id"]]))
    first = json.loads(capsys.readouterr().out)
    cmd_attachments_rm(_args(tmp_path, ids=[big["id"]]))
    second = json.loads(capsys.readouterr().out)

    assert first == {"removed": [big["id"]], "freed_bytes": 9000}
    assert second == {"removed": [big["id"]], "freed_bytes": 0}
    assert attachments.read_meta(root, big["id"]) is not None


def test_rm_unknown_id_fails_on_stderr(tmp_path, capsys):
    _seed(tmp_path)

    with pytest.raises(SystemExit):
        cmd_attachments_rm(_args(tmp_path, ids=["nope"]))
    err = capsys.readouterr().err
    assert "error" in json.loads(err)


def test_rm_validates_every_id_before_removing_any(tmp_path, capsys):
    root, big, small, _ = _seed(tmp_path)

    with pytest.raises(SystemExit):
        cmd_attachments_rm(_args(tmp_path, ids=[big["id"], "nope"]))

    capsys.readouterr()
    assert not attachments.is_removed(root, big["id"])  # nothing was removed
    assert not attachments.is_removed(root, small["id"])
