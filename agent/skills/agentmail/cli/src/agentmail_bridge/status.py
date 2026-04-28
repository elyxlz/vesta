"""agentmail status: show current configuration."""

from __future__ import annotations

import json
import os

import click

from agentmail_bridge.config import (
    AGENTMAIL_API_KEY_ENV,
    NOTIFICATIONS_DIR,
    load_config,
)


@click.command("status")
def status_cmd() -> None:
    cfg = load_config()
    if not cfg:
        click.echo("not configured. Run `agentmail setup` first")
        return
    inbound = sorted(
        NOTIFICATIONS_DIR.glob("*-agentmail-message.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    last = None
    if inbound:
        last_path = inbound[0]
        try:
            last_payload = json.loads(last_path.read_text())
        except json.JSONDecodeError:
            last_payload = {}
        last = {
            "path": str(last_path),
            "timestamp": last_payload["timestamp"] if "timestamp" in last_payload else None,
        }
    out = {
        "address": cfg["email_address"] if "email_address" in cfg else None,
        "inbox_id": cfg["inbox_id"] if "inbox_id" in cfg else None,
        "username": cfg["username"] if "username" in cfg else None,
        "webhook_url": cfg["webhook_url"] if "webhook_url" in cfg else None,
        "webhook_id": cfg["webhook_id"] if "webhook_id" in cfg else None,
        "api_key_set": bool(os.environ.get(AGENTMAIL_API_KEY_ENV, "").strip()),
        "vestad_tunnel": os.environ["VESTAD_TUNNEL"] if "VESTAD_TUNNEL" in os.environ else "",
        "last_inbound": last,
    }
    click.echo(json.dumps(out, indent=2))
