"""agentmail send: send mail via the AgentMail REST API."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from agentmail import api
from agentmail.config import load_config


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
@click.option(
    "--html-file",
    "html_file",
    type=click.Path(exists=True, dir_okay=False),
    help="Optional HTML body",
)
@click.option(
    "--in-reply-to",
    "in_reply_to",
    default=None,
    help="Message-Id of the email being replied to (sets In-Reply-To + References for threading)",
)
@click.option("--cc", default=None, help="CC recipient(s)")
@click.option("--bcc", default=None, help="BCC recipient(s)")
def send_cmd(
    to_addr: str,
    subject: str,
    body_text: str,
    body_file: str | None,
    html_file: str | None,
    in_reply_to: str | None,
    cc: str | None,
    bcc: str | None,
) -> None:
    """Send an email."""
    if body_file:
        body_text = Path(body_file).read_text()
    body_html = Path(html_file).read_text() if html_file else None

    if not body_text and not body_html:
        click.echo("error: empty body. Provide --body, --body-file, or --html-file", err=True)
        sys.exit(2)

    cfg = load_config()
    if "inbox_id" not in cfg:
        click.echo("error: skill not configured. Run `agentmail setup` first", err=True)
        sys.exit(2)

    try:
        result = api.send_message(
            cfg["inbox_id"],
            to_addr=to_addr,
            subject=subject,
            text=body_text,
            html=body_html,
            in_reply_to=in_reply_to,
            cc=cc,
            bcc=bcc,
        )
    except Exception as e:
        click.echo(json.dumps({"ok": False, "error": str(e)}), err=True)
        sys.exit(1)

    click.echo(json.dumps({"ok": True, "result": result}, indent=2))
