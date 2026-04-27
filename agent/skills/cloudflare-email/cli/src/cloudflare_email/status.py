"""cloudflare-email status: show current configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from cloudflare_email.config import (
    NOTIFICATIONS_DIR,
    email_address,
    load_config,
)


@click.command("status")
def status_cmd() -> None:
    cfg = load_config()
    if not cfg:
        click.echo("not configured. Run `cloudflare-email setup` first")
        return
    inbound = sorted(
        NOTIFICATIONS_DIR.glob("*-cloudflare-email-message.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    last = None
    if inbound:
        last_path = inbound[0]
        last = {
            "path": str(last_path),
            "received_at": json.loads(last_path.read_text()).get("received_at"),
        }
    out = {
        "address": cfg.get("address") or email_address(),
        "domain": cfg.get("domain"),
        "worker_name": cfg.get("worker_name"),
        "inbound_url": cfg.get("inbound_url"),
        "last_inbound": last,
        "vestad_tunnel": os.environ.get("VESTAD_TUNNEL", ""),
    }
    click.echo(json.dumps(out, indent=2))
