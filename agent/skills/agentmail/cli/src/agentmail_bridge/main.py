"""agentmail CLI entry point.

Vesta-specific verbs (setup / serve / status / teardown) are handled in
Python. Anything else is passed through to the official AgentMail npm CLI
installed locally at NPM_CLI_BIN — so the agent only sees one binary on
PATH.
"""

from __future__ import annotations

import os
import sys

import click

from agentmail_bridge import serve, setup, status, teardown
from agentmail_bridge.config import NPM_CLI_BIN


VESTA_VERBS = {"setup", "serve", "status", "teardown", "--help", "-h"}


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli() -> None:
    """Vesta-side bridge to AgentMail.

    Vesta verbs: setup, serve, status, teardown.

    Anything else is passed through to the official `agentmail` CLI (installed
    locally by `agentmail setup`). Common examples:

      agentmail inboxes:messages send --inbox-id <id> --to <addr> --subject ... --text ...
      agentmail inboxes:messages reply --inbox-id <id> --message-id <id> --text ...
      agentmail inboxes:threads list --inbox-id <id>
      agentmail webhooks list
    """


cli.add_command(setup.setup_cmd)
cli.add_command(serve.serve_cmd)
cli.add_command(status.status_cmd)
cli.add_command(teardown.teardown_cmd)


def _passthrough(args: list[str]) -> None:
    """Exec the official npm CLI with the given args. Replaces this process."""
    if not NPM_CLI_BIN.exists():
        click.echo(
            f"error: official AgentMail CLI not installed at {NPM_CLI_BIN}.\n  Run `agentmail setup` first; it installs the CLI locally.",
            err=True,
        )
        sys.exit(127)
    os.execv(str(NPM_CLI_BIN), [str(NPM_CLI_BIN)] + args)


def main() -> None:
    args = sys.argv[1:]
    first = args[0] if args else ""
    if not first or first in VESTA_VERBS:
        cli(args)
        return
    _passthrough(args)


if __name__ == "__main__":
    main()
