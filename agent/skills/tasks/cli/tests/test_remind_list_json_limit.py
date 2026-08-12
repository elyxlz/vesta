"""`tasks remind list` never silently truncates, in either format.

JSON is consumed by scripts asking absence questions ("is anything scheduled for X?"), so a hidden
page size would answer them wrongly. Only an explicit --limit caps JSON output.

The human table keeps its page size, because dumping hundreds of rows at a terminal is worse than
paging them. But the same absence question gets asked of the table, by eye or by grep, and a table
that simply stops is indistinguishable from a table that ended: the last row it prints looks exactly
like the last row that exists. So the table names the total when it held rows back. Documenting the
page size in --help is not enough, because the reader who needs to know is the one already looking
at a table that appears complete."""

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


REMINDER_COUNT = 60  # comfortably past the table page size of 50


def _seed_reminders(cfg: Config, count: int) -> None:
    for i in range(count):
        commands.remind_set(cfg, commands.ReminderSpec(message=f"r{i}", in_minutes=10 + i))


def _run_remind_list(monkeypatch, capsys, cfg: Config, *argv: str) -> str:
    monkeypatch.setattr(cli, "Config", lambda: cfg)
    monkeypatch.setattr(cli.daemon, "live_pid", lambda: 1)
    monkeypatch.setattr(sys, "argv", ["tasks", "remind", "list", *argv])
    cli.main()
    return capsys.readouterr().out


@pytest.mark.parametrize("json_flag", ["--json", "--json-pretty"])
def test_json_returns_every_reminder(tmp_config: Config, monkeypatch, capsys, json_flag: str):
    _seed_reminders(tmp_config, REMINDER_COUNT)
    listed = json.loads(_run_remind_list(monkeypatch, capsys, tmp_config, json_flag))
    assert len(listed) == REMINDER_COUNT


def test_json_honors_an_explicit_limit(tmp_config: Config, monkeypatch, capsys):
    _seed_reminders(tmp_config, REMINDER_COUNT)
    listed = json.loads(_run_remind_list(monkeypatch, capsys, tmp_config, "--json", "--limit", "10"))
    assert len(listed) == 10


def test_table_output_keeps_its_page_size(tmp_config: Config, monkeypatch, capsys):
    _seed_reminders(tmp_config, REMINDER_COUNT)
    table = _run_remind_list(monkeypatch, capsys, tmp_config).strip()
    rows, _, footer = table.rpartition("\n")
    assert len(rows.splitlines()) == cli.REMIND_LIST_PAGE_SIZE
    assert footer.startswith("...")


def test_table_names_the_total_it_truncated_to(tmp_config: Config, monkeypatch, capsys):
    _seed_reminders(tmp_config, REMINDER_COUNT)
    footer = _run_remind_list(monkeypatch, capsys, tmp_config).strip().splitlines()[-1]
    assert f"showing {cli.REMIND_LIST_PAGE_SIZE} of {REMINDER_COUNT}" in footer
    assert "--json" in footer, "the footer has to name a way to see the rest"


def test_table_stays_silent_when_nothing_was_held_back(tmp_config: Config, monkeypatch, capsys):
    _seed_reminders(tmp_config, 3)
    table = _run_remind_list(monkeypatch, capsys, tmp_config).strip()
    assert len(table.splitlines()) == 3
    assert "showing" not in table


def test_an_explicit_limit_is_the_caller_asking_and_stays_silent(tmp_config: Config, monkeypatch, capsys):
    _seed_reminders(tmp_config, REMINDER_COUNT)
    table = _run_remind_list(monkeypatch, capsys, tmp_config, "--limit", "5").strip()
    assert len(table.splitlines()) == 5
    assert "showing" not in table
