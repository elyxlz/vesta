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


def test_get_task_fields_returns_requested_subset(tmp_config: Config):
    task = commands.add_task(tmp_config, title="multi", priority="low")
    assert commands.get_task_fields(tmp_config, task_id=task["id"], fields=["status"]) == {"status": "pending"}
    got = commands.get_task_fields(tmp_config, task_id=task["id"], fields=["title", "priority", "status"])
    assert got == {"title": "multi", "priority": 1, "status": "pending"}


def test_get_task_fields_reads_metadata_only_when_requested(tmp_config: Config, monkeypatch):
    task = commands.add_task(tmp_config, title="heavy notes", initial_metadata="big notes here")

    read_calls: list[str] = []
    original = commands._read_metadata
    monkeypatch.setattr(commands, "_read_metadata", lambda d, i: (read_calls.append(i), original(d, i))[1])

    commands.get_task_fields(tmp_config, task_id=task["id"], fields=["status", "title", "metadata_path"])
    assert read_calls == []  # metadata_path alone does NOT trigger a file read

    got = commands.get_task_fields(tmp_config, task_id=task["id"], fields=["metadata"])
    assert got == {"metadata": "big notes here"}
    assert read_calls == [task["id"]]


def test_get_task_fields_unknown_field_raises(tmp_config: Config):
    task = commands.add_task(tmp_config, title="x")
    with pytest.raises(ValueError, match="Unknown field"):
        commands.get_task_fields(tmp_config, task_id=task["id"], fields=["bogus"])
