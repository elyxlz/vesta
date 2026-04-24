"""Unit tests for commands.get_task_fields — field selector without full metadata reads."""

from pathlib import Path

import pytest

from tasks_cli import commands, db
from tasks_cli.config import Config


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    cfg = Config(data_dir=tmp_path / "tasks", log_dir=tmp_path / "tasks" / "logs")
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    db.init_db(cfg.data_dir)
    return cfg


def test_get_task_fields_single_db_field(tmp_config: Config):
    task = commands.add_task(tmp_config, title="hello", priority="high")
    got = commands.get_task_fields(tmp_config, task_id=task["id"], fields=["status"])
    assert got == {"status": "pending"}


def test_get_task_fields_multiple_fields(tmp_config: Config):
    task = commands.add_task(tmp_config, title="multi", priority="low")
    got = commands.get_task_fields(tmp_config, task_id=task["id"], fields=["title", "priority", "status"])
    assert got["title"] == "multi"
    assert got["priority"] == 1
    assert got["status"] == "pending"


def test_get_task_fields_metadata_reads_file(tmp_config: Config):
    task = commands.add_task(tmp_config, title="with notes", initial_metadata="big notes here")
    got = commands.get_task_fields(tmp_config, task_id=task["id"], fields=["metadata"])
    assert got == {"metadata": "big notes here"}


def test_get_task_fields_metadata_missing_returns_none(tmp_config: Config):
    task = commands.add_task(tmp_config, title="no notes")
    got = commands.get_task_fields(tmp_config, task_id=task["id"], fields=["metadata"])
    assert got == {"metadata": None}


def test_get_task_fields_skips_metadata_read_when_not_requested(tmp_config: Config, monkeypatch):
    task = commands.add_task(tmp_config, title="heavy notes", initial_metadata="x" * 10_000)

    read_calls: list[str] = []
    original = commands._read_metadata

    def spy(data_dir, task_id):
        read_calls.append(task_id)
        return original(data_dir, task_id)

    monkeypatch.setattr(commands, "_read_metadata", spy)

    commands.get_task_fields(tmp_config, task_id=task["id"], fields=["status", "title"])
    assert read_calls == []

    commands.get_task_fields(tmp_config, task_id=task["id"], fields=["metadata"])
    assert read_calls == [task["id"]]


def test_get_task_fields_metadata_path_does_not_read_file(tmp_config: Config, monkeypatch):
    task = commands.add_task(tmp_config, title="pathonly", initial_metadata="content")
    read_calls: list[str] = []
    original = commands._read_metadata
    monkeypatch.setattr(commands, "_read_metadata", lambda d, i: (read_calls.append(i), original(d, i))[1])

    got = commands.get_task_fields(tmp_config, task_id=task["id"], fields=["metadata_path"])
    assert got["metadata_path"].endswith(f"{task['id']}.md")
    assert read_calls == []


def test_get_task_fields_unknown_field_raises(tmp_config: Config):
    task = commands.add_task(tmp_config, title="x")
    with pytest.raises(ValueError, match="Unknown field"):
        commands.get_task_fields(tmp_config, task_id=task["id"], fields=["bogus"])


def test_get_task_fields_missing_task_raises(tmp_config: Config):
    with pytest.raises(ValueError, match="not found"):
        commands.get_task_fields(tmp_config, task_id="missing", fields=["status"])
