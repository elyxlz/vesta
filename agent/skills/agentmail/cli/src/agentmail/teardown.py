"""agentmail teardown: delete inbox + webhook + clear local config."""

from __future__ import annotations

import sys

import click

from agentmail import api
from agentmail.config import load_config, save_config


@click.command("teardown")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def teardown_cmd(yes: bool) -> None:
    cfg = load_config()
    if "inbox_id" not in cfg:
        click.echo("nothing to teardown.")
        return
    if not yes:
        click.confirm(
            f"this will delete inbox {cfg['inbox_id']} and its webhook. continue?",
            abort=True,
        )

    if "webhook_id" in cfg and cfg["webhook_id"]:
        click.echo(f"deleting webhook {cfg['webhook_id']}")
        try:
            api.delete_webhook(cfg["webhook_id"])
        except Exception as e:
            click.echo(f"  warn: webhook delete failed: {e}", err=True)

    click.echo(f"deleting inbox {cfg['inbox_id']}")
    try:
        api.delete_inbox(cfg["inbox_id"])
    except Exception as e:
        click.echo(f"  inbox delete failed: {e}", err=True)
        sys.exit(1)

    save_config({})
    click.echo("teardown complete. AgentMail account itself was not touched.")
