"""agentmail teardown: delete the inbox + webhook + clear local config."""

from __future__ import annotations

import os
import sys

import click
from agentmail import AgentMail

from agentmail_bridge.config import AGENTMAIL_API_KEY_ENV, load_config, save_config


@click.command("teardown")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def teardown_cmd(yes: bool) -> None:
    cfg = load_config()
    if "inbox_id" not in cfg:
        click.echo("nothing to teardown.")
        return

    key = os.environ.get(AGENTMAIL_API_KEY_ENV, "").strip()
    if not key:
        click.echo(
            f"error: {AGENTMAIL_API_KEY_ENV} not set; cannot call AgentMail to delete.",
            err=True,
        )
        sys.exit(1)

    if not yes:
        click.confirm(
            f"this will delete inbox {cfg['inbox_id']} and its webhook. continue?",
            abort=True,
        )

    client = AgentMail(api_key=key)

    if "webhook_id" in cfg and cfg["webhook_id"]:
        click.echo(f"deleting webhook {cfg['webhook_id']}")
        try:
            client.webhooks.delete(webhook_id=cfg["webhook_id"])
        except Exception as e:
            click.echo(f"  warn: webhook delete failed: {e}", err=True)

    click.echo(f"deleting inbox {cfg['inbox_id']}")
    try:
        client.inboxes.delete(inbox_id=cfg["inbox_id"])
    except Exception as e:
        click.echo(f"  inbox delete failed: {e}", err=True)
        sys.exit(1)

    save_config({})
    click.echo("teardown complete. AgentMail account itself was not touched.")
