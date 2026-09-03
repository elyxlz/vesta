"""`reminders update` answers a retime attempt with the command that retimes.

A one-shot's fire time moves with `snooze`, in place and under the same id. `update` does not carry
the retime flags, so reaching for them there used to die in argparse as "unrecognized arguments",
which reads as "a one-shot cannot be retimed" and invites delete-and-recreate. That mints a new id:
the old id's metadata file at `~/.reminders/metadata/<id>.md` is orphaned, every reference to the old
id (including the ones inside reminder bodies, where no grep of the source tree reaches) goes stale,
and created_at resets, so a reminder carried for weeks reads as new."""

import sys

import pytest
from reminders_cli import cli, commands
from reminders_cli.config import Config

RETIME_ARGS = [
    ["--at", "2026-09-13T18:00:00"],
    ["--at=2026-09-13T18:00:00"],
    ["--at", "2026-09-13T18:00:00", "--tz", "America/Cancun"],
    ["--in-minutes", "30"],
    ["--in-hours", "10"],
    ["--in-days", "2"],
]


@pytest.mark.parametrize("retime_args", RETIME_ARGS, ids=" ".join)
def test_a_retime_flag_names_snooze_and_the_reminder_id(tmp_config: Config, retime_args: list[str]):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="golf sets", scheduled_datetime="2026-09-13T13:00:00+00:00"))

    with pytest.raises(ValueError) as excinfo:
        cli._update_cmd(tmp_config, [reminder["id"], *retime_args])

    message = str(excinfo.value)
    assert f"reminders snooze {reminder['id']}" in message
    assert retime_args[0].split("=")[0] in message


def test_the_pointer_carries_the_id_given_as_a_flag(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="golf sets", in_hours=1))

    with pytest.raises(ValueError, match=f"reminders snooze {reminder['id']}"):
        cli._update_cmd(tmp_config, ["--id", reminder["id"], "--at", "2026-09-13T18:00:00"])


def test_a_retime_without_an_id_still_points_at_snooze(tmp_config: Config):
    with pytest.raises(ValueError, match=r"reminders snooze <id>"):
        cli._update_cmd(tmp_config, ["--at", "2026-09-13T18:00:00"])


def test_the_pointer_never_swallows_a_plain_update(tmp_config: Config):
    """The guard reads flags only: a message that merely mentions one is still an ordinary update."""
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="old", in_hours=1))

    result = cli._update_cmd(tmp_config, [reminder["id"], "--message", "ask --at the desk, in-hours only"])

    assert result["message"] == "ask --at the desk, in-hours only"
    assert result["id"] == reminder["id"]


def test_a_retime_changes_nothing_before_it_is_refused(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="golf sets", scheduled_datetime="2026-09-13T13:00:00+00:00"))

    with pytest.raises(ValueError):
        cli._update_cmd(tmp_config, [reminder["id"], "--message", "moved", "--at", "2026-09-13T18:00:00"])

    unchanged = commands.remind_get(tmp_config, reminder_id=reminder["id"])
    assert unchanged["message"] == "golf sets"
    assert unchanged["schedule"] == reminder["schedule"]


def test_the_update_help_names_snooze(tmp_config: Config, monkeypatch, capsys):
    """`update --help` is where an agent looks before concluding a retime is impossible."""
    monkeypatch.setattr(cli, "Config", lambda: tmp_config)
    monkeypatch.setattr(cli.daemon, "live_pid", lambda: 1)
    monkeypatch.setattr(sys, "argv", ["reminders", "update", "--help"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0
    assert "reminders snooze <id> --at" in capsys.readouterr().out


def test_the_route_the_pointer_names_retimes_in_place(tmp_config: Config):
    """The whole point of the pointer: the command it names keeps the id, the metadata and created_at.

    A one-shot set for 13:00 UTC by an agent in one zone, moved to 18:00 in the zone the user has
    travelled to, is the case that costs the most when it is done by delete-and-recreate."""
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="golf sets", scheduled_datetime="2026-09-13T13:00:00+00:00"))
    notes = tmp_config.data_dir / "metadata"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / f"{reminder['id']}.md").write_text("# plan\nGuest Services desk\n")

    result = commands.remind_snooze(
        tmp_config, reminder_id=reminder["id"], spec=commands.SnoozeSpec(at="2026-09-13T18:00:00", tz="America/Cancun")
    )

    assert result["id"] == reminder["id"]
    assert result["schedule"] == "once at 2026-09-13T23:00:00+00:00"  # 18:00 in a UTC-5 zone
    after = commands.remind_get(tmp_config, reminder_id=reminder["id"])
    assert after["created_at"] == reminder["created_at"]
    assert after["metadata_content"] == "# plan\nGuest Services desk\n"
