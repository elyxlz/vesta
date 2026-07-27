"""The discord daemon subcommand delegates to the shared runner."""

import pathlib as pl

from discord_cli import cli


def test_daemon_lifecycle_args_declare_a_portless_session():
    args = cli.daemon_lifecycle_args("start")

    assert args[0] == str(pl.Path.home() / "agent/skills/vestad/scripts/daemon-lifecycle")
    assert args[1] == "start"
    assert args[args.index("--session") + 1] == "discord"
    assert "--port-mode" not in args
    assert args[args.index("--") + 1 : args.index("--") + 3] == ["discord", "serve"]
