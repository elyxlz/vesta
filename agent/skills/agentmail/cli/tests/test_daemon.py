"""The agentmail daemon verb hands the bridge to the shared runner as a public vestad service,
so the runner registers the port and the session expands it into `agentmail serve`."""

import pathlib as pl

import pytest
from agentmail_bridge import daemon


def _flag(args: list[str], name: str) -> str:
    return args[args.index(name) + 1]


def test_the_shared_runner_is_the_program_being_launched():
    args = daemon.daemon_lifecycle_args("start")
    assert args[0] == str(pl.Path.home() / "agent" / "skills" / "vestad" / "scripts" / "daemon-lifecycle")


@pytest.mark.parametrize("action", ["start", "stop", "restart", "status"])
def test_every_verb_reaches_the_runner_as_its_first_argument(action):
    assert daemon.daemon_lifecycle_args(action)[1] == action


def test_the_screen_session_is_named_after_the_skill():
    assert _flag(daemon.daemon_lifecycle_args("start"), "--session") == "agentmail"


def test_the_bridge_registers_as_a_public_service_because_webhooks_arrive_uncredentialed():
    args = daemon.daemon_lifecycle_args("start")
    assert _flag(args, "--service") == "agentmail"
    assert _flag(args, "--port-mode") == "public"


def test_the_launch_command_defers_the_port_to_the_runner():
    args = daemon.daemon_lifecycle_args("start")
    assert args[args.index("--") + 1 :] == ["agentmail", "serve", "--port", "$PORT"]
