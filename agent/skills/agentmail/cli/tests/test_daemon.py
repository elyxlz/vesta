"""The agentmail daemon subcommand delegates to the shared runner as a public service."""

import pathlib as pl

from agentmail_bridge import daemon


def test_daemon_lifecycle_args_declare_a_public_service():
    args = daemon.daemon_lifecycle_args("start")

    assert args[0] == str(pl.Path.home() / "agent/skills/vestad/scripts/daemon-lifecycle")
    assert args[1] == "start"
    assert args[args.index("--session") + 1] == "agentmail"
    assert args[args.index("--service") + 1] == "agentmail"
    assert args[args.index("--port-mode") + 1] == "public"
    assert args[args.index("--") + 1 :] == ["agentmail", "serve", "--port", "$PORT"]
