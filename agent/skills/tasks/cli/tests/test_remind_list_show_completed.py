"""`tasks remind list` hides completed reminders by default and reveals them with --show-completed.

A one-shot reminder that has fired is marked completed and drops off the default list, so a
self-chaining reminder cannot re-read its own body once it has fired. --show-completed makes the
fired copy retrievable, mirroring `tasks list --show-completed` on the task side.
"""

import json
import sys
from pathlib import Path

import pytest
from tasks_cli import cli, commands, db
from tasks_cli.config import Config


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    cfg = Config(data_dir=tmp_path / "tasks", log_dir=tmp_path / "tasks" / "logs")
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    db.init_db(cfg.data_dir)
    return cfg


def _mark_completed(cfg: Config, reminder_id: str) -> None:
    with db.get_db(cfg.data_dir) as conn:
        conn.execute("UPDATE reminders SET completed = 1 WHERE id = ?", (reminder_id,))
        conn.commit()


def _run(monkeypatch, capsys, cfg: Config, *argv: str) -> str:
    monkeypatch.setattr(cli, "Config", lambda: cfg)
    monkeypatch.setattr(cli.daemon, "live_pid", lambda: 1)
    monkeypatch.setattr(sys, "argv", ["tasks", "remind", "list", *argv])
    cli.main()
    return capsys.readouterr().out


def test_completed_reminder_hidden_by_default(tmp_config: Config, monkeypatch, capsys):
    done = commands.remind_set(tmp_config, commands.ReminderSpec(message="fired", in_minutes=10))
    commands.remind_set(tmp_config, commands.ReminderSpec(message="pending", in_minutes=20))
    _mark_completed(tmp_config, done["id"])

    listed = json.loads(_run(monkeypatch, capsys, tmp_config, "--json"))
    messages = [r["message"] for r in listed]
    assert "pending" in messages
    assert "fired" not in messages


def test_show_completed_reveals_it(tmp_config: Config, monkeypatch, capsys):
    done = commands.remind_set(tmp_config, commands.ReminderSpec(message="fired", in_minutes=10))
    _mark_completed(tmp_config, done["id"])

    listed = json.loads(_run(monkeypatch, capsys, tmp_config, "--json", "--show-completed"))
    by_msg = {r["message"]: r for r in listed}
    assert "fired" in by_msg
    assert by_msg["fired"]["status"] == "completed"


def test_show_completed_respects_task_filter(tmp_config: Config, monkeypatch, capsys):
    task = commands.add_task(tmp_config, title="T")
    linked = commands.remind_set(tmp_config, commands.ReminderSpec(message="linked-fired", in_minutes=10, task_id=task["id"]))
    other = commands.remind_set(tmp_config, commands.ReminderSpec(message="loose-fired", in_minutes=10))
    _mark_completed(tmp_config, linked["id"])
    _mark_completed(tmp_config, other["id"])

    listed = json.loads(_run(monkeypatch, capsys, tmp_config, "--json", "--show-completed", "--task", task["id"]))
    messages = [r["message"] for r in listed]
    assert messages == ["linked-fired"]
