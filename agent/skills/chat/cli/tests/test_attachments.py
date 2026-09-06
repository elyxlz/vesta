"""Tests for the attachment blob store: copy-in under an id minted by the node, blob-only removal (the
"no longer available" state), the id gate, and the GC sweep. The store is pure filesystem functions
under one root; the CLI and the replica layer on top of it."""

import os
import time

import pytest
from chat_cli.attachments import (
    UnknownAttachmentError,
    blob_path,
    human_size,
    is_removed,
    read_meta,
    remove_blob,
    sanitize_filename,
    store_copy,
    sweep,
)

from .attachment_fixture import stored_attachment


def _stored(tmp_path, root, data: bytes, name="photo.jpg"):
    """One finalized attachment in `root`, from a file written under tmp_path."""
    source = tmp_path / name
    source.write_bytes(data)
    return stored_attachment(root, source)["id"]


def test_store_copy_publishes_a_blob_under_the_id_it_carries(tmp_path):
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-fake")
    meta = stored_attachment(tmp_path / "store", source)
    assert meta["name"] == "report.pdf"
    assert meta["mime"] == "application/pdf"
    assert meta["size"] == len(b"%PDF-fake")
    assert read_meta(tmp_path / "store", meta["id"]) == meta
    source.unlink()  # the copy stands alone
    assert blob_path(tmp_path / "store", meta["id"]).read_bytes() == b"%PDF-fake"


def test_store_copy_refuses_an_id_the_store_cannot_hold(tmp_path):
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-fake")
    with pytest.raises(UnknownAttachmentError):
        store_copy(tmp_path / "store", source, {"id": "not-a-store-id", "name": "report.pdf", "mime": "application/pdf", "size": 9})


def test_read_meta_is_none_for_an_id_this_store_does_not_hold(tmp_path):
    root = tmp_path / "store"
    assert read_meta(root, "nope") is None
    assert read_meta(root, "a" * 32) is None
    assert read_meta(root, _stored(tmp_path, root, b"abcd")) is not None


def test_sanitize_filename_strips_traversal_and_never_returns_empty():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("a/b\\c.txt") == "c.txt"
    assert sanitize_filename("...") == "file"
    assert sanitize_filename("") == "file"
    assert sanitize_filename("evil\x00\nname.png") == "evilname.png"
    assert len(sanitize_filename("x" * 500)) <= 120


def test_remove_blob_frees_bytes_keeps_meta_and_is_idempotent(tmp_path):
    attachment_id = _stored(tmp_path, tmp_path / "store", b"abcdef")
    root = tmp_path / "store"
    assert not is_removed(root, attachment_id)
    assert remove_blob(root, attachment_id) == 6
    assert is_removed(root, attachment_id)
    assert read_meta(root, attachment_id) is not None  # meta survives for the history tile
    assert remove_blob(root, attachment_id) == 0  # already-removed is a no-op
    with pytest.raises(UnknownAttachmentError):
        remove_blob(root, "nope")


def test_sweep_removes_unreferenced_old_dirs_and_keeps_tombstones(tmp_path):
    root = tmp_path / "store"
    referenced = _stored(tmp_path, root, b"kept", name="kept.bin")
    unreferenced = _stored(tmp_path, root, b"orphan", name="orphan.bin")
    removed_dir = _stored(tmp_path, root, b"gone-bytes", name="gone.bin")
    remove_blob(root, removed_dir)
    unfinished = root / ("b" * 32)  # a directory nothing finished writing: no meta, nothing points at it
    unfinished.mkdir()
    (unfinished / "half.bin").write_bytes(b"ab")
    far_future = 10**12  # every dir is far older than the max age at this "now"

    swept = sweep(root, far_future, lambda attachment_id: attachment_id == referenced)

    assert set(swept) == {unreferenced, "b" * 32}
    assert read_meta(root, referenced) is not None
    assert read_meta(root, removed_dir) is not None  # removed-blob dirs are kept (tombstone)
    assert not unfinished.exists()


def test_sweep_keeps_a_fresh_unreferenced_attachment(tmp_path):
    root = tmp_path / "store"
    fresh = _stored(tmp_path, root, b"just-arrived")

    assert sweep(root, time.time(), lambda _: False) == []
    assert (root / fresh).exists()


def test_human_size():
    assert human_size(340) == "340 B"
    assert human_size(2 * 1024) == "2.0 kB"
    assert human_size(int(2.1 * 1024 * 1024)) == "2.1 MB"
    assert human_size(3 * 1024 * 1024 * 1024) == "3.0 GB"


def test_a_copied_in_control_filename_round_trips(tmp_path):
    """The record file is dot-prefixed and a stored name never keeps a leading dot, so a user file
    named like the store's own record cannot clobber it."""
    source = tmp_path / "meta.json"
    source.write_bytes(b'{"user": "export"}')
    meta = stored_attachment(tmp_path / "store", source)
    assert not meta["name"].startswith(".")
    assert blob_path(tmp_path / "store", meta["id"]).read_bytes() == b'{"user": "export"}'
    assert read_meta(tmp_path / "store", meta["id"]) == meta


def test_sweep_ages_by_last_activity_not_directory_creation(tmp_path):
    """A blob rewritten in place leaves the directory's own mtime alone, so age reads the newest file
    mtime instead: an attachment just refreshed must never be reaped."""
    root = tmp_path / "store"
    attachment_id = _stored(tmp_path, root, b"abcd")
    directory = root / attachment_id
    ancient = 1000.0
    for child in directory.iterdir():
        os.utime(child, (ancient, ancient))
    os.utime(directory, (ancient, ancient))
    assert sweep(root, time.time(), lambda _: False) == [attachment_id]

    attachment_id = _stored(tmp_path, root, b"abcd", name="fresh.bin")
    directory = root / attachment_id
    os.utime(directory, (ancient, ancient))  # only the directory is old; its files are current

    assert sweep(root, time.time(), lambda _: False) == []
    assert directory.exists()


def test_malformed_id_never_touches_the_filesystem(tmp_path):
    assert read_meta(tmp_path, "../escape") is None
    assert not is_removed(tmp_path, "../escape")
    with pytest.raises(UnknownAttachmentError):
        blob_path(tmp_path, "../escape")
    with pytest.raises(UnknownAttachmentError):
        remove_blob(tmp_path, "../escape")
