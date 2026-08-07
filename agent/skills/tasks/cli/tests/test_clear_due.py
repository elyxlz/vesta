"""Clearing a due date.

`clear` unsets a task's due date and deletes the auto reminders regenerated from it (see
`db._create_auto_reminders_for_existing`). Only an explicit clear touches the date, and it cannot
be combined with a due-setting field.
"""

from contextlib import closing

import pytest
from tasks_cli import commands, db
from tasks_cli.config import Config


def _pending_auto_reminders(config: Config, task_id: str) -> int:
    with closing(db.get_db(config.data_dir)) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM reminders WHERE task_id = ? AND auto_generated = 1",
            (task_id,),
        ).fetchone()
    return row[0]


def test_clear_due_removes_date_and_auto_reminders(tmp_config: Config):
    config = tmp_config
    task = commands.add_task(
        config,
        title="backburner item",
        due=commands.DueSpec(due_in_days=30),
    )
    task_id = task["id"]

    assert task["due_date"] is not None
    assert _pending_auto_reminders(config, task_id) > 0

    updated = commands.update_task(
        config,
        task_id=task_id,
        due=commands.DueSpec(clear=True),
    )

    assert updated["due_date"] is None
    assert _pending_auto_reminders(config, task_id) == 0


def test_clear_due_does_not_need_a_timezone(tmp_config: Config):
    """`due_datetime` requires a timezone; clearing must not inherit that requirement."""
    config = tmp_config
    task = commands.add_task(config, title="item", due=commands.DueSpec(due_in_hours=5))

    updated = commands.update_task(config, task_id=task["id"], due=commands.DueSpec(clear=True))

    assert updated["due_date"] is None


def test_clear_due_rejects_a_conflicting_due_offset(tmp_config: Config):
    """`clear` and a due-setting field together are contradictory: reject, do not silently pick one."""
    config = tmp_config
    task = commands.add_task(config, title="item", due=commands.DueSpec(due_in_days=3))

    with pytest.raises(ValueError, match="clear"):
        commands.update_task(config, task_id=task["id"], due=commands.DueSpec(clear=True, due_in_days=10))


def test_update_without_due_spec_leaves_the_date_alone(tmp_config: Config):
    """A plain edit must not be read as a clear: only an explicit request touches the due date."""
    config = tmp_config
    task = commands.add_task(config, title="item", due=commands.DueSpec(due_in_days=3))
    before = task["due_date"]

    updated = commands.update_task(config, task_id=task["id"], title="renamed")

    assert updated["due_date"] == before
    assert _pending_auto_reminders(config, task["id"]) > 0
