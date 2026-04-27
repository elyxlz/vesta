"""agentmail CLI entry point."""

import sys

import click

from agentmail import send, serve, setup, status, teardown


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli() -> None:
    """Send/receive email as the agent via AgentMail (managed inbox-per-agent)."""


cli.add_command(setup.setup_cmd)
cli.add_command(send.send_cmd)
cli.add_command(serve.serve_cmd)
cli.add_command(status.status_cmd)
cli.add_command(teardown.teardown_cmd)


def main() -> None:
    cli(sys.argv[1:])


if __name__ == "__main__":
    main()
