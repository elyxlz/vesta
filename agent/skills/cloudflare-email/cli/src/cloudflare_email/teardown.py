"""cloudflare-email teardown: remove routing rules + worker."""

from __future__ import annotations

import os
import subprocess

import click

from cloudflare_email import cf_api
from cloudflare_email.config import load_config, save_config


@click.command("teardown")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def teardown_cmd(yes: bool) -> None:
    cfg = load_config()
    if not cfg.get("worker_name"):
        click.echo("nothing to teardown.")
        return
    if not yes:
        click.confirm(
            f"this will remove routing rules and worker {cfg['worker_name']}. continue?",
            abort=True,
        )
    rules = cf_api.list_routing_rules(cfg["zone_id"])
    target_names = {f"agent-{cfg['address']}", f"agent-{cfg['local']}-subaddress"}
    for rule in rules:
        if rule.name in target_names:
            click.echo(f"deleting rule {rule.name}")
            cf_api.delete_routing_rule(cfg["zone_id"], rule.tag)
    env = os.environ.copy()
    env["CLOUDFLARE_API_TOKEN"] = cf_api.cf_api_token()
    env["CLOUDFLARE_ACCOUNT_ID"] = cfg["account_id"]
    try:
        subprocess.run(
            ["wrangler", "delete", "--name", cfg["worker_name"], "--force"],
            env=env,
            check=False,
        )
    except FileNotFoundError:
        click.echo("warn: wrangler not found, leaving worker in place", err=True)
    save_config({})
    click.echo("teardown complete.")
