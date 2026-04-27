"""cloudflare-email CLI entry point."""

import sys
import click

from cloudflare_email import setup, send, serve, status, subscribe, teardown


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli() -> None:
    """Email send/receive for the agent via Cloudflare Email Service."""


cli.add_command(setup.setup_cmd)
cli.add_command(setup.reconcile_cmd)
cli.add_command(send.send_cmd)
cli.add_command(serve.serve_cmd)
cli.add_command(status.status_cmd)
cli.add_command(subscribe.subscribe_cmd)
cli.add_command(teardown.teardown_cmd)


def main() -> None:
    cli(sys.argv[1:])


if __name__ == "__main__":
    main()
