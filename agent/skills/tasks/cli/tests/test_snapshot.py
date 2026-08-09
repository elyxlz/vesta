"""Unit tests for commands.snapshot_tasks: a version-controllable export of the task store."""

import json
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


def test_snapshot_writes_tasks_and_their_metadata(tmp_config: Config, tmp_path: Path):
    task = commands.add_task(tmp_config, title="ship it", priority="high", initial_metadata="the reasoning")
    out = tmp_path / "snap"

    result = commands.snapshot_tasks(tmp_config, out_dir=out)

    assert result["tasks"] == 1 and result["metadata"] == 1
    rows = json.loads((out / "tasks.json").read_text())
    assert [row["title"] for row in rows] == ["ship it"]
    assert (out / "metadata" / f"{task['id']}.md").read_text() == "the reasoning"


def test_snapshot_is_deterministic_so_an_unchanged_store_produces_no_diff(tmp_config: Config, tmp_path: Path):
    """The point of the export is that it can be committed on a schedule, which only works if a run
    that changes nothing writes the same bytes."""
    commands.add_task(tmp_config, title="b", initial_metadata="two")
    commands.add_task(tmp_config, title="a", initial_metadata="one")
    out = tmp_path / "snap"

    commands.snapshot_tasks(tmp_config, out_dir=out)
    first = (out / "tasks.json").read_bytes()
    commands.snapshot_tasks(tmp_config, out_dir=out)

    assert (out / "tasks.json").read_bytes() == first


def test_snapshot_sorts_by_id_not_insertion_order(tmp_config: Config, tmp_path: Path):
    """Ids are random, so without the sort the same store exports in a different order each run and
    every snapshot looks like a change."""
    ids = sorted(commands.add_task(tmp_config, title=f"t{n}")["id"] for n in range(5))
    out = tmp_path / "snap"

    commands.snapshot_tasks(tmp_config, out_dir=out)

    assert [row["id"] for row in json.loads((out / "tasks.json").read_text())] == ids


def test_snapshot_prunes_metadata_for_a_deleted_task(tmp_config: Config, tmp_path: Path):
    task = commands.add_task(tmp_config, title="temporary", initial_metadata="notes")
    out = tmp_path / "snap"
    commands.snapshot_tasks(tmp_config, out_dir=out)
    commands.delete_task(tmp_config, task_id=task["id"])

    result = commands.snapshot_tasks(tmp_config, out_dir=out)

    assert result["pruned"] == 1
    assert not (out / "metadata" / f"{task['id']}.md").exists()


def test_snapshot_omits_the_absolute_metadata_path(tmp_config: Config, tmp_path: Path):
    """The live path is machine-specific, so exporting it would make the snapshot differ between
    boxes for no reason."""
    commands.add_task(tmp_config, title="pathless", initial_metadata="notes")
    out = tmp_path / "snap"

    commands.snapshot_tasks(tmp_config, out_dir=out)

    assert "metadata_path" not in json.loads((out / "tasks.json").read_text())[0]
