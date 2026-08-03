"""A hand-written reminder message must survive a postpone.

`delete_auto_reminders` (called by postpone and by any due-date change) deletes exactly the rows
flagged `auto_generated = 1`. That flag means "machine-owned, safe to regenerate", so rewriting a
reminder's message has to clear it, otherwise the rewritten text is destroyed by the next postpone
with no warning and no way to tell from `remind list` that it was at risk.
"""

from contextlib import closing

from tasks_cli import commands, db
from tasks_cli.config import Config


def _reminders(config: Config, task_id: str) -> list[dict]:
    with closing(db.get_db(config.data_dir)) as conn:
        rows = conn.execute(
            "SELECT id, message, auto_generated FROM reminders WHERE task_id = ? AND completed = 0",
            (task_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _task_with_auto_reminders(config: Config) -> tuple[str, dict]:
    task = commands.add_task(config, title="original title", due=commands.DueSpec(due_in_days=3))
    autos = _reminders(config, task["id"])
    assert autos, "a task with a due date must start with auto reminders"
    return task["id"], autos[0]


def test_rewriting_a_reminder_takes_ownership_of_it(tmp_config: Config):
    task_id, auto = _task_with_auto_reminders(tmp_config)
    assert auto["auto_generated"] == 1

    commands.remind_update(tmp_config, reminder_id=auto["id"], message="hand written checkpoint")

    rewritten = next(r for r in _reminders(tmp_config, task_id) if r["id"] == auto["id"])
    assert rewritten["message"] == "hand written checkpoint"
    assert rewritten["auto_generated"] == 0, "rewriting a reminder must clear the machine-owned flag"


def test_a_rewritten_reminder_survives_a_postpone(tmp_config: Config):
    task_id, auto = _task_with_auto_reminders(tmp_config)
    commands.remind_update(tmp_config, reminder_id=auto["id"], message="hand written checkpoint")

    commands.postpone_task(tmp_config, task_id=task_id, in_days=7)

    surviving = [r["message"] for r in _reminders(tmp_config, task_id)]
    assert "hand written checkpoint" in surviving, (
        "postpone deletes auto_generated rows, so a rewritten reminder that kept the flag is "
        f"silently destroyed; surviving messages were {surviving}"
    )


def test_postpone_still_replaces_untouched_auto_reminders(tmp_config: Config):
    """The fix must not stop postpone regenerating the reminders it does own."""
    task_id, _ = _task_with_auto_reminders(tmp_config)
    before = {r["id"] for r in _reminders(tmp_config, task_id)}

    commands.postpone_task(tmp_config, task_id=task_id, in_days=7)

    after = _reminders(tmp_config, task_id)
    assert after, "postpone must leave a fresh set of auto reminders"
    assert all(r["auto_generated"] == 1 for r in after)
    assert not (before & {r["id"] for r in after}), "untouched auto reminders should be regenerated"


def test_rewriting_relabels_the_schedule(tmp_config: Config):
    """An owned reminder must not still describe itself as auto-generated. `remind list` renders
    schedule_type, so leaving it makes a hand-written row read `auto: 1 day before due` while its
    marker says otherwise."""
    _, auto = _task_with_auto_reminders(tmp_config)
    assert auto["auto_generated"] == 1

    result = commands.remind_update(tmp_config, reminder_id=auto["id"], message="mine now")

    with closing(db.get_db(tmp_config.data_dir)) as conn:
        row = conn.execute("SELECT schedule_type, scheduled_time FROM reminders WHERE id = ?", (auto["id"],)).fetchone()

    assert not row["schedule_type"].startswith("auto: "), f"an owned reminder still claims to be auto-generated: {row['schedule_type']}"
    assert row["schedule_type"] == f"once at {row['scheduled_time']}"
    assert result["schedule"] == row["schedule_type"], "the returned schedule must not be the stale label"
