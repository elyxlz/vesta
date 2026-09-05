"""Tests for the attachment blob store: offset-addressed staging, idempotent finalize, ingest-by-copy
for agent sends, blob-only removal (the 410 state), and the GC sweep. The store is pure filesystem
functions under one root; the service and CLI layer routes on top of it."""

import time

import pytest
from chat_cli.attachments import (
    MAX_ATTACHMENT_BYTES,
    OffsetMismatchError,
    SizeError,
    SizeMismatchError,
    UnknownAttachmentError,
    append_at,
    blob_path,
    create_session,
    finalize,
    human_size,
    ingest_file,
    is_removed,
    read_meta,
    remove_blob,
    sanitize_filename,
    staged_size,
    sweep,
    upload_status,
)


def _create(root, name="photo.jpg", mime="image/jpeg", size=10, extra=None):
    return create_session(root, name, mime, size, extra if extra is not None else {})


def _upload(root, data: bytes, name="photo.jpg", mime="image/jpeg"):
    attachment_id = _create(root, name=name, mime=mime, size=len(data))
    append_at(root, attachment_id, 0, data)
    finalize(root, attachment_id)
    return attachment_id


def test_create_session_rejects_size_over_cap(tmp_path):
    with pytest.raises(SizeError):
        _create(tmp_path, size=MAX_ATTACHMENT_BYTES + 1)


def test_sequential_offset_appends_accumulate(tmp_path):
    attachment_id = _create(tmp_path, size=8)
    assert append_at(tmp_path, attachment_id, 0, b"abcd") == 4
    assert append_at(tmp_path, attachment_id, 4, b"efgh") == 8
    assert staged_size(tmp_path, attachment_id) == 8


def test_stale_offset_raises_with_received_and_stages_nothing(tmp_path):
    attachment_id = _create(tmp_path, size=8)
    append_at(tmp_path, attachment_id, 0, b"abcd")
    with pytest.raises(OffsetMismatchError) as exc_info:
        append_at(tmp_path, attachment_id, 2, b"xxxx")
    assert exc_info.value.received == 4
    assert staged_size(tmp_path, attachment_id) == 4


def test_replayed_append_reads_as_delivered(tmp_path):
    """A retried PUT whose bytes already landed gets received == offset + len, the lost-response case."""
    attachment_id = _create(tmp_path, size=8)
    append_at(tmp_path, attachment_id, 0, b"abcd")
    with pytest.raises(OffsetMismatchError) as exc_info:
        append_at(tmp_path, attachment_id, 0, b"abcd")
    assert exc_info.value.received == 0 + 4


def test_append_beyond_declared_size_is_rejected(tmp_path):
    attachment_id = _create(tmp_path, size=4)
    with pytest.raises(SizeError):
        append_at(tmp_path, attachment_id, 0, b"abcdefgh")
    assert staged_size(tmp_path, attachment_id) == 0


def test_append_to_unknown_id_raises(tmp_path):
    with pytest.raises(UnknownAttachmentError):
        append_at(tmp_path, "nope", 0, b"x")
    with pytest.raises(UnknownAttachmentError):
        staged_size(tmp_path, "nope")


def test_finalize_rejects_size_mismatch(tmp_path):
    attachment_id = _create(tmp_path, size=8)
    append_at(tmp_path, attachment_id, 0, b"abcd")
    with pytest.raises(SizeMismatchError):
        finalize(tmp_path, attachment_id)
    assert read_meta(tmp_path, attachment_id) is None


def test_finalize_renames_blob_and_is_idempotent(tmp_path):
    attachment_id = _create(tmp_path, size=4, extra={"width": 10, "height": 20})
    append_at(tmp_path, attachment_id, 0, b"abcd")
    meta = finalize(tmp_path, attachment_id)
    assert meta["id"] == attachment_id
    assert meta["name"] == "photo.jpg"
    assert meta["mime"] == "image/jpeg"
    assert meta["size"] == 4
    assert meta["width"] == 10 and meta["height"] == 20
    assert blob_path(tmp_path, attachment_id).read_bytes() == b"abcd"
    assert finalize(tmp_path, attachment_id) == meta  # idempotent no-op


def test_read_meta_is_none_before_finalize_and_for_unknown(tmp_path):
    attachment_id = _create(tmp_path, size=4)
    assert read_meta(tmp_path, attachment_id) is None
    assert read_meta(tmp_path, "nope") is None
    append_at(tmp_path, attachment_id, 0, b"abcd")
    finalize(tmp_path, attachment_id)
    assert read_meta(tmp_path, attachment_id) is not None


def test_ingest_file_copies_and_guesses_mime(tmp_path):
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-fake")
    meta = ingest_file(tmp_path / "store", source, None)
    assert meta["name"] == "report.pdf"
    assert meta["mime"] == "application/pdf"
    assert meta["size"] == len(b"%PDF-fake")
    assert blob_path(tmp_path / "store", meta["id"]).read_bytes() == b"%PDF-fake"
    source.unlink()  # the copy stands alone
    assert blob_path(tmp_path / "store", meta["id"]).read_bytes() == b"%PDF-fake"


def test_ingest_file_rejects_oversize_and_missing_source(tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 8)
    with pytest.raises(SizeError):
        ingest_file(tmp_path / "store", big, None, max_bytes=4)
    with pytest.raises(FileNotFoundError):
        ingest_file(tmp_path / "store", tmp_path / "absent.bin", None)


def test_sanitize_filename_strips_traversal_and_never_returns_empty():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("a/b\\c.txt") == "c.txt"
    assert sanitize_filename("...") == "file"
    assert sanitize_filename("") == "file"
    assert sanitize_filename("evil\x00\nname.png") == "evilname.png"
    assert len(sanitize_filename("x" * 500)) <= 120


def test_remove_blob_frees_bytes_keeps_meta_and_is_idempotent(tmp_path):
    attachment_id = _upload(tmp_path, b"abcdef")
    assert not is_removed(tmp_path, attachment_id)
    assert remove_blob(tmp_path, attachment_id) == 6
    assert is_removed(tmp_path, attachment_id)
    assert read_meta(tmp_path, attachment_id) is not None  # meta survives for the 410 + history
    assert remove_blob(tmp_path, attachment_id) == 0  # already-removed is a no-op
    with pytest.raises(UnknownAttachmentError):
        remove_blob(tmp_path, "nope")


def test_sweep_removes_stale_sessions_and_unreferenced_old_dirs(tmp_path):
    stale_session = _create(tmp_path, size=4)
    append_at(tmp_path, stale_session, 0, b"ab")
    referenced = _upload(tmp_path, b"kept")
    unreferenced = _upload(tmp_path, b"orphan")
    removed_dir = _upload(tmp_path, b"gone-bytes")
    remove_blob(tmp_path, removed_dir)
    far_future = 10**12  # every dir is far older than the max age at this "now"

    swept = sweep(tmp_path, far_future, lambda attachment_id: attachment_id == referenced)

    assert set(swept) == {stale_session, unreferenced}
    assert read_meta(tmp_path, referenced) is not None
    assert read_meta(tmp_path, removed_dir) is not None  # removed-blob dirs are kept (tombstone)
    assert not (tmp_path / stale_session).exists()
    assert not (tmp_path / unreferenced).exists()


def test_sweep_keeps_fresh_sessions(tmp_path):
    fresh_session = _create(tmp_path, size=4)

    swept = sweep(tmp_path, time.time(), lambda _: False)
    assert swept == []
    assert (tmp_path / fresh_session).exists()


def test_upload_status_tracks_staging_and_finalized(tmp_path):
    attachment_id = _create(tmp_path, size=8)
    append_at(tmp_path, attachment_id, 0, b"abcd")
    assert upload_status(tmp_path, attachment_id) == (4, 8, False)
    append_at(tmp_path, attachment_id, 4, b"efgh")
    finalize(tmp_path, attachment_id)
    assert upload_status(tmp_path, attachment_id) == (8, 8, True)
    with pytest.raises(UnknownAttachmentError):
        upload_status(tmp_path, "nope")


def test_human_size():
    assert human_size(340) == "340 B"
    assert human_size(2 * 1024) == "2.0 kB"
    assert human_size(int(2.1 * 1024 * 1024)) == "2.1 MB"
    assert human_size(3 * 1024 * 1024 * 1024) == "3.0 GB"


def test_control_filenames_cannot_clobber_the_store(tmp_path):
    """Dot-prefixed control files plus dot-stripping sanitization: a user file named like a store
    record round-trips untouched."""
    for hostile in ("session.json", "meta.json", ".part", ".meta.json", ".session.json"):
        attachment_id = _create(tmp_path, name=hostile, size=4)
        append_at(tmp_path, attachment_id, 0, b"data")
        meta = finalize(tmp_path, attachment_id)
        assert not meta["name"].startswith(".")
        assert blob_path(tmp_path, attachment_id).read_bytes() == b"data"
        assert not is_removed(tmp_path, attachment_id)
        assert read_meta(tmp_path, attachment_id) == meta


def test_ingest_control_filename_round_trips(tmp_path):
    source = tmp_path / "meta.json"
    source.write_bytes(b'{"user": "export"}')
    meta = ingest_file(tmp_path / "store", source, None)
    assert blob_path(tmp_path / "store", meta["id"]).read_bytes() == b'{"user": "export"}'
    assert read_meta(tmp_path / "store", meta["id"]) == meta


def test_sweep_ages_by_last_activity_not_directory_creation(tmp_path):
    """A slow upload still appending chunks must never be reaped: age reads the newest file mtime."""
    import os

    session = _create(tmp_path, size=8)
    append_at(tmp_path, session, 0, b"abcd")
    ancient = 1000.0
    directory = tmp_path / session
    os.utime(directory, (ancient, ancient))
    for child in directory.iterdir():
        os.utime(child, (ancient, ancient))
    # A fresh chunk arrives: activity moves to now even though the dir mtime stays old.
    os.utime(directory, (ancient, ancient))
    append_at(tmp_path, session, 4, b"ef")
    os.utime(directory, (ancient, ancient))

    assert sweep(tmp_path, time.time(), lambda _: False) == []
    assert (tmp_path / session).exists()


def test_malformed_id_never_touches_the_filesystem(tmp_path):
    assert read_meta(tmp_path, "../escape") is None
    assert not is_removed(tmp_path, "../escape")
    with pytest.raises(UnknownAttachmentError):
        staged_size(tmp_path, "../escape")
    with pytest.raises(UnknownAttachmentError):
        remove_blob(tmp_path, "../escape")
