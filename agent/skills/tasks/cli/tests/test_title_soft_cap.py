"""A task title past the soft cap warns on stderr and points at metadata, but the write always
happens: the cap is advisory because a legitimately long title exists. stdout stays the command's
JSON result either way."""

import json
import sys
from pathlib import Path

import pytest
from tasks_cli import cli, commands, db
from tasks_cli.config import Config

LONG_TITLE = "reclaim the expense: " + "detail " * 20  # well past the 100-char soft cap
SHORT_TITLE = "Reclaim the expense"


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    cfg = Config(data_dir=tmp_path / "tasks", log_dir=tmp_path / "tasks" / "logs")
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    db.init_db(cfg.data_dir)
    return cfg


def _run_tasks(monkeypatch, capsys, cfg: Config, *argv: str):
    monkeypatch.setattr(cli, "Config", lambda: cfg)
    monkeypatch.setattr(cli.daemon, "live_pid", lambda: 1)
    monkeypatch.setattr(sys, "argv", ["tasks", *argv])
    cli.main()
    return capsys.readouterr()


def test_add_long_title_warns_but_still_creates(tmp_config: Config, monkeypatch, capsys):
    out = _run_tasks(monkeypatch, capsys, tmp_config, "add", LONG_TITLE)
    warning = json.loads(out.err)["warning"]
    assert "metadata" in warning
    created = json.loads(out.out)
    assert created["title"] == LONG_TITLE
    assert commands.get_task(tmp_config, task_id=created["id"])["title"] == LONG_TITLE


def test_add_short_title_does_not_warn(tmp_config: Config, monkeypatch, capsys):
    out = _run_tasks(monkeypatch, capsys, tmp_config, "add", SHORT_TITLE)
    assert out.err == ""
    assert json.loads(out.out)["title"] == SHORT_TITLE


def test_update_long_title_warns_but_still_applies(tmp_config: Config, monkeypatch, capsys):
    task = commands.add_task(tmp_config, title=SHORT_TITLE)
    out = _run_tasks(monkeypatch, capsys, tmp_config, "update", task["id"], "--title", LONG_TITLE)
    assert "metadata" in json.loads(out.err)["warning"]
    assert commands.get_task(tmp_config, task_id=task["id"])["title"] == LONG_TITLE


def test_update_short_title_does_not_warn(tmp_config: Config, monkeypatch, capsys):
    task = commands.add_task(tmp_config, title=SHORT_TITLE)
    out = _run_tasks(monkeypatch, capsys, tmp_config, "update", task["id"], "--title", "Renamed")
    assert out.err == ""
    assert commands.get_task(tmp_config, task_id=task["id"])["title"] == "Renamed"
