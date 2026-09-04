import os
import pathlib as pl
import time

import pytest
from vesta_browser import artifacts as a
from vesta_browser import sessions as s
from vesta_browser.runtime_paths import load_paths

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


@pytest.fixture
def session(tmp_path):
    table = s.load_table(load_paths({}, tmp_path))
    return s.resolve_session(table, "research", None)


def test_a_path_printed_on_stdout_is_moved_into_the_artifact_dir(session):
    started = time.time() - 1
    shot = session.scratch_dir / "tmp" / "shot.png"
    shot.parent.mkdir()
    shot.write_bytes(PNG)
    found, warnings = a.collect(session, f"saved {shot}\n", started, now=lambda: "2026-09-04T12:00:00Z")
    assert warnings == []
    assert len(found) == 1 and found[0]["kind"] == "screenshot" and found[0]["mime_type"] == "image/png"
    assert found[0]["path"].startswith(str(session.artifact_dir)) and found[0]["bytes"] == len(PNG)
    assert found[0]["captured_at"] == "2026-09-04T12:00:00Z"
    assert not shot.exists() and pl.Path(found[0]["path"]).exists()


def test_new_files_in_the_artifact_dir_are_reported_without_a_stdout_mention(session):
    started = time.time() - 1
    (session.artifact_dir / "shot-1.jpg").write_bytes(JPEG)
    found, _ = a.collect(session, "", started, now=lambda: "t")
    assert [x["mime_type"] for x in found] == ["image/jpeg"]


def test_a_path_outside_the_session_dirs_is_skipped_with_a_warning(session, tmp_path):
    outside = tmp_path / "secret.png"
    outside.write_bytes(PNG)
    found, warnings = a.collect(session, f"{outside}\n", time.time() - 1, now=lambda: "t")
    assert found == [] and warnings == [f"artifact_skipped: {outside} is outside the session directories"]
    assert outside.exists()


def test_a_file_older_than_the_exec_is_ignored(session):
    old = session.scratch_dir / "old.png"
    old.write_bytes(PNG)
    os.utime(old, (1_600_000_000, 1_600_000_000))
    found, warnings = a.collect(session, f"{old}\n", time.time() - 1, now=lambda: "t")
    assert found == [] and warnings == []


def test_wrong_magic_and_oversize_are_skipped(session, monkeypatch):
    monkeypatch.setattr(a, "ARTIFACT_MAX_BYTES", 16)
    fake = session.scratch_dir / "fake.png"
    fake.write_bytes(b"not an image")
    big = session.scratch_dir / "big.png"
    big.write_bytes(PNG)
    _, warnings = a.collect(session, f"{fake}\n{big}\n", time.time() - 1, now=lambda: "t")
    assert warnings == [
        f"artifact_skipped: {fake} is not a supported image",
        f"artifact_skipped: {big} exceeds 16 bytes",
    ]


def test_prune_removes_only_files_past_retention(tmp_path):
    paths = load_paths({}, tmp_path)
    table = s.load_table(paths)
    session = s.resolve_session(table, "research", None)
    old = session.artifact_dir / "old.png"
    old.write_bytes(PNG)
    stamp = time.time() - (a.ARTIFACT_RETENTION_DAYS + 1) * 86400
    os.utime(old, (stamp, stamp))
    fresh = session.artifact_dir / "fresh.png"
    fresh.write_bytes(PNG)
    assert a.prune(paths) == 1
    assert not old.exists() and fresh.exists()
