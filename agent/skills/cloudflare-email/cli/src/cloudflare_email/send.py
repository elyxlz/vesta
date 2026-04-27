"""cloudflare-email send: send mail via the Cloudflare Email Sending API."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from cloudflare_email import cf_api
from cloudflare_email.config import email_address, load_config


@click.command("send")
@click.option("--to", "to_addr", required=True, help="Recipient email address")
@click.option("--subject", required=True, help="Subject line")
@click.option("--body", "body_text", default="", help="Plain text body (or use --body-file)")
@click.option(
    "--body-file",
    "body_file",
    type=click.Path(exists=True, dir_okay=False),
    help="Read body from file",
)
@click.option("--html-file", "html_file", type=click.Path(exists=True, dir_okay=False), help="Optional HTML body")
@click.option(
    "--in-reply-to",
    "in_reply_to",
    default=None,
    help="Message-Id of the email being replied to (sets In-Reply-To + References for threading)",
)
@click.option("--from-addr", "from_addr", default=None, help="Override sender (default: agent's address)")
def send_cmd(
    to_addr: str,
    subject: str,
    body_text: str,
    body_file: str | None,
    html_file: str | None,
    in_reply_to: str | None,
    from_addr: str | None,
) -> None:
    """Send an email."""
    if body_file:
        body_text = Path(body_file).read_text()
    body_html = Path(html_file).read_text() if html_file else None

    if not body_text:
        click.echo("error: empty body. Provide --body or --body-file", err=True)
        sys.exit(2)

    cfg = load_config()
    if "account_id" not in cfg:
        click.echo("error: skill not configured. Run `cloudflare-email setup` first", err=True)
        sys.exit(2)
    if "outbound_enabled" in cfg and not cfg["outbound_enabled"]:
        click.echo(
            "error: outbound email is disabled (inbound-only setup, or Email "
            "Sending enable failed at setup time).\n"
            "  Cloudflare Email Sending requires Workers Paid ($5/mo). "
            "Subscribe and re-run `cloudflare-email setup` to enable.",
            err=True,
        )
        sys.exit(2)
    account_id = cfg["account_id"]

    sender = from_addr or email_address()
    try:
        result = cf_api.send_email(
            account_id,
            from_addr=sender,
            to_addr=to_addr,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            in_reply_to=in_reply_to,
        )
    except Exception as e:
        click.echo(json.dumps({"ok": False, "error": str(e)}), err=True)
        sys.exit(1)

    click.echo(json.dumps({"ok": True, "result": result}, indent=2))
