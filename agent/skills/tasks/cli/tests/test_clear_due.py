"""Clearing a due date.

`clear` unsets a task's due date, which silences its checkpoint ladder since checkpoints derive
from the date. Only an explicit clear touches the date, and it cannot be combined with a
due-setting field.
"""

import pytest
from tasks_cli import commands
from tasks_cli.config import Config


def test_clear_due_removes_the_date(tmp_config: Config):
    config = tmp_config
    task = commands.add_task(
        config,
        subject="backburner item",
        due=commands.DueSpec(due_in_days=30),
    )
    task_id = task["id"]

    assert task["due_date"] is not None

    updated = commands.update_task(
        config,
        task_id=task_id,
        due=commands.DueSpec(clear=True),
    )

    assert updated["due_date"] is None


def test_clear_due_does_not_need_a_timezone(tmp_config: Config):
    """`due_datetime` requires a timezone; clearing must not inherit that requirement."""
    config = tmp_config
    task = commands.add_task(config, subject="item", due=commands.DueSpec(due_in_hours=5))

    updated = commands.update_task(config, task_id=task["id"], due=commands.DueSpec(clear=True))

    assert updated["due_date"] is None


def test_clear_due_rejects_a_conflicting_due_offset(tmp_config: Config):
    """`clear` and a due-setting field together are contradictory: reject, do not silently pick one."""
    config = tmp_config
    task = commands.add_task(config, subject="item", due=commands.DueSpec(due_in_days=3))

    with pytest.raises(ValueError, match="clear"):
        commands.update_task(config, task_id=task["id"], due=commands.DueSpec(clear=True, due_in_days=10))


def test_update_without_due_spec_leaves_the_date_alone(tmp_config: Config):
    """A plain edit must not be read as a clear: only an explicit request touches the due date."""
    config = tmp_config
    task = commands.add_task(config, subject="item", due=commands.DueSpec(due_in_days=3))
    before = task["due_date"]

    updated = commands.update_task(config, task_id=task["id"], subject="renamed")

    assert updated["due_date"] == before
