"""`reminders get` returns one reminder by id, deleted ones included, and --field prints raw values."""

import sys

import pytest
from reminders_cli import cli, commands
from reminders_cli.config import Config


def test_get_returns_the_reminder(tmp_config: Config):
    created = commands.remind_set(tmp_config, commands.ReminderSpec(message="m", in_hours=1))
    got = commands.remind_get(tmp_config, reminder_id=created["id"])
    assert got["id"] == created["id"]
    assert got["message"] == "m"
    assert got["next_run"] == created["next_run"]
    assert got["status"] == "pending"
    assert got["deleted_at"] is None


def test_get_resolves_a_deleted_reminder(tmp_config: Config):
    created = commands.remind_set(tmp_config, commands.ReminderSpec(message="m", in_hours=1))
    commands.remind_delete(tmp_config, reminder_id=created["id"])
    got = commands.remind_get(tmp_config, reminder_id=created["id"])
    assert got["deleted_at"] is not None


def test_get_unknown_id_errors(tmp_config: Config):
    with pytest.raises(ValueError, match="not found"):
        commands.remind_get(tmp_config, reminder_id="nope")


def test_get_field_prints_the_raw_value(tmp_config: Config, monkeypatch, capsys):
    created = commands.remind_set(tmp_config, commands.ReminderSpec(message="just this", in_hours=1))
    monkeypatch.setattr(cli, "Config", lambda: tmp_config)
    monkeypatch.setattr(cli.daemon, "live_pid", lambda: 1)
    monkeypatch.setattr(sys, "argv", ["reminders", "get", created["id"], "--field", "message"])
    cli.main()
    assert capsys.readouterr().out.strip() == "just this"
