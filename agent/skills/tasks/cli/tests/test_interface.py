"""Unit tests for the agent-facing interface: one time vocabulary across the task commands."""

import json
import sys
from datetime import UTC, datetime, timedelta

from tasks_cli import cli, commands, db
from tasks_cli.config import Config


def _run_cli(monkeypatch, capsys, cfg: Config, *argv: str) -> tuple[str, str]:
    monkeypatch.setattr(cli, "Config", lambda: cfg)
    monkeypatch.setattr(cli.daemon, "live_pid", lambda: 1)
    monkeypatch.setattr(sys, "argv", ["tasks", *argv])
    cli.main()
    captured = capsys.readouterr()
    return captured.out, captured.err


# ---------------------------------------------------------------------------
# One time vocabulary
# ---------------------------------------------------------------------------


def test_create_accepts_at_and_tz(tmp_config: Config, monkeypatch, capsys):
    out, _ = _run_cli(monkeypatch, capsys, tmp_config, "create", "meet", "--at", "2027-01-01T10:00:00", "--tz", "UTC")
    task = json.loads(out)
    assert db.parse_datetime(task["due_date"]) == datetime(2027, 1, 1, 10, tzinfo=UTC)


def test_create_accepts_in_hours(tmp_config: Config, monkeypatch, capsys):
    out, _ = _run_cli(monkeypatch, capsys, tmp_config, "create", "soon", "--in-hours", "4")
    task = json.loads(out)
    delta = db.parse_datetime(task["due_date"]) - datetime.now(UTC)
    assert timedelta(hours=3, minutes=55) < delta < timedelta(hours=4, minutes=5)


def test_create_still_accepts_the_due_spellings(tmp_config: Config, monkeypatch, capsys):
    out, _ = _run_cli(monkeypatch, capsys, tmp_config, "create", "meet", "--due-datetime", "2027-01-01T10:00:00", "--timezone", "UTC")
    assert db.parse_datetime(json.loads(out)["due_date"]) == datetime(2027, 1, 1, 10, tzinfo=UTC)


def test_update_accepts_at_and_tz(tmp_config: Config, monkeypatch, capsys):
    task = commands.add_task(tmp_config, subject="movable")
    out, _ = _run_cli(monkeypatch, capsys, tmp_config, "update", task["id"], "--at", "2027-02-01T09:00:00", "--tz", "UTC")
    assert db.parse_datetime(json.loads(out)["due_date"]) == datetime(2027, 2, 1, 9, tzinfo=UTC)
