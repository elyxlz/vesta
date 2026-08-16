"""`reminders list` hides completed reminders by default and reveals them with --show-completed.

A one-shot reminder that has fired is marked completed and drops off the default list, so a
self-chaining reminder cannot re-read its own body once it has fired. --show-completed makes the
fired copy retrievable.
"""

import json
import sys
from contextlib import closing

from reminders_cli import cli, commands, db
from reminders_cli.config import Config


def _mark_completed(cfg: Config, reminder_id: str) -> None:
    with closing(db.get_db(cfg.data_dir)) as conn:
        conn.execute("UPDATE reminders SET completed = 1 WHERE id = ?", (reminder_id,))
        conn.commit()


def _run(monkeypatch, capsys, cfg: Config, *argv: str) -> str:
    monkeypatch.setattr(cli, "Config", lambda: cfg)
    monkeypatch.setattr(cli.daemon, "live_pid", lambda: 1)
    monkeypatch.setattr(sys, "argv", ["reminders", "list", *argv])
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


def test_old_fired_rows_never_page_out_pending_ones(tmp_config: Config, monkeypatch, capsys):
    """Fired one-shots sort after pending ones, newest fired first, so a backlog of old fired rows
    cannot fill the table page and hide the live rows or the just-fired one being recovered."""
    for i in range(cli.REMIND_LIST_PAGE_SIZE + 10):
        old = commands.remind_set(tmp_config, commands.ReminderSpec(message=f"old-fired-{i}", in_minutes=10 + i))
        _mark_completed(tmp_config, old["id"])
    just_fired = commands.remind_set(tmp_config, commands.ReminderSpec(message="just-fired", in_minutes=500))
    _mark_completed(tmp_config, just_fired["id"])
    commands.remind_set(tmp_config, commands.ReminderSpec(message="still-pending", in_minutes=600))

    table = _run(monkeypatch, capsys, tmp_config, "--show-completed")
    first_rows = table.strip().splitlines()[:2]
    assert "still-pending" in first_rows[0]
    assert "just-fired" in first_rows[1]


def test_table_marks_fired_rows(tmp_config: Config, monkeypatch, capsys):
    done = commands.remind_set(tmp_config, commands.ReminderSpec(message="already-ran", in_minutes=10))
    _mark_completed(tmp_config, done["id"])
    commands.remind_set(tmp_config, commands.ReminderSpec(message="not-yet", in_minutes=20))

    lines = _run(monkeypatch, capsys, tmp_config, "--show-completed").strip().splitlines()
    fired_lines = [line for line in lines if "[fired]" in line]
    assert len(fired_lines) == 1
    assert "already-ran" in fired_lines[0]


def test_a_revealed_fired_row_can_be_deleted(tmp_config: Config, monkeypatch, capsys):
    """An id --show-completed prints has to be actionable, or the flag reveals rows it cannot act on."""
    done = commands.remind_set(tmp_config, commands.ReminderSpec(message="fired", in_minutes=10))
    _mark_completed(tmp_config, done["id"])

    assert commands.remind_delete(tmp_config, reminder_id=done["id"])["status"] == "deleted"
    listed = json.loads(_run(monkeypatch, capsys, tmp_config, "--json", "--show-completed"))
    assert listed == []
