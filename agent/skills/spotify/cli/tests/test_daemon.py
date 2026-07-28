"""The spotify daemon verb hands the organize watcher to the shared runner, declaring a screen
session that is not the skill name and registering no vestad service."""

import pathlib as pl

import pytest
from spotify_cli import cli


def _flag(args: list[str], name: str) -> str:
    return args[args.index(name) + 1]


def test_the_shared_runner_is_the_program_being_launched():
    args = cli.daemon_lifecycle_args("start")
    assert args[0] == str(pl.Path.home() / "agent" / "skills" / "vestad" / "scripts" / "daemon-lifecycle")


@pytest.mark.parametrize("action", ["start", "stop", "restart", "status"])
def test_every_verb_reaches_the_runner_as_its_first_argument(action):
    assert cli.daemon_lifecycle_args(action)[1] == action


def test_the_screen_session_is_the_watcher_rather_than_the_skill_name():
    assert _flag(cli.daemon_lifecycle_args("start"), "--session") == "spotify-watch"


def test_the_watcher_registers_no_port_and_needs_no_stop_marker():
    args = cli.daemon_lifecycle_args("start")
    assert "--service" not in args
    assert "--port-mode" not in args
    assert "--stop-marker" not in args


def test_the_launch_command_is_the_organize_watcher():
    args = cli.daemon_lifecycle_args("start")
    assert args[args.index("--") + 1 :] == ["spotify", "organize", "watch"]
