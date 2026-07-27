"""agentmail daemon: lifecycle for the bridge service, delegated to the shared runner.

The bridge is a public service because AgentMail's webhooks reach it from outside the tunnel,
so it registers public and the runner hands the resolved port to `agentmail serve`.
"""

from __future__ import annotations

import pathlib as pl
import subprocess
import sys

import click

DAEMON_LIFECYCLE = pl.Path.home() / "agent" / "skills" / "vestad" / "scripts" / "daemon-lifecycle"


def daemon_lifecycle_args(action: str) -> list[str]:
    """Argv for the shared runner. `$PORT` stays a literal: the runner exports the port it
    registered into the session, and the shell inside the session expands it."""
    return [
        str(DAEMON_LIFECYCLE),
        action,
        "--session",
        "agentmail",
        "--service",
        "agentmail",
        "--port-mode",
        "public",
        "--",
        "agentmail",
        "serve",
        "--port",
        "$PORT",
    ]


@click.command("daemon")
@click.argument("action", type=click.Choice(["start", "stop", "restart", "status"]))
def daemon_cmd(action: str) -> None:
    sys.exit(subprocess.run(daemon_lifecycle_args(action), check=False).returncode)
