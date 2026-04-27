"""agentmail setup: programmatic sign-up, inbox creation, webhook registration."""

from __future__ import annotations

import os
import secrets
import sys

import click

from agentmail import api
from agentmail.config import (
    AGENTMAIL_API_KEY_ENV,
    AGENTMAIL_WEBHOOK_SECRET_ENV,
    agent_name,
    bashrc_set,
    load_config,
    save_config,
    webhook_secret,
)


def _resolve_webhook_url() -> str:
    """Public URL for AgentMail to POST inbound mail to. Reads VESTAD_TUNNEL
    from env (set by vestad on container start)."""
    tunnel = os.environ["VESTAD_TUNNEL"].strip() if "VESTAD_TUNNEL" in os.environ else ""
    if not tunnel:
        return ""
    return f"{tunnel.rstrip('/')}/agents/{agent_name()}/agentmail"


@click.command("setup")
@click.option("--username", default=None, help="Local-part for the agent's address (default: $AGENT_NAME lowercased)")
@click.option("--human-email", "human_email", default=None, help="Email address for OTP verification (skip-prompt mode)")
@click.option("--skip-signup", is_flag=True, help="Skip the sign-up flow; assume AGENTMAIL_API_KEY is already set")
def setup_cmd(username: str | None, human_email: str | None, skip_signup: bool) -> None:
    """Interactive setup. Run once."""
    click.echo("agentmail setup")
    click.echo("=" * 40)

    if not username:
        username = agent_name().lower()

    # 1. sign-up (unless we already have a key)
    have_key = bool(os.environ.get(AGENTMAIL_API_KEY_ENV, "").strip())
    if skip_signup or have_key:
        if have_key:
            click.echo("AGENTMAIL_API_KEY already set; skipping sign-up.")
        else:
            click.echo(
                f"--skip-signup passed but {AGENTMAIL_API_KEY_ENV} is empty.\n"
                f"  Sign up at https://console.agentmail.to and "
                f"`export {AGENTMAIL_API_KEY_ENV}=<key>` first.",
                err=True,
            )
            sys.exit(2)
    else:
        click.echo("\nstarting sign-up...")
        if not human_email:
            human_email = click.prompt(
                "your email (where AgentMail will send the OTP)",
            )
        try:
            api.sign_up(human_email=human_email, username=username)
        except RuntimeError as e:
            click.echo(f"  sign-up failed: {e}", err=True)
            click.echo(
                "\nIf the API rejected sign-up, fall back to manual signup:\n"
                "  1. Use the browser skill to sign up at https://console.agentmail.to\n"
                "  2. Generate an API key in the dashboard\n"
                f"  3. export {AGENTMAIL_API_KEY_ENV}=<key>\n"
                "  4. agentmail setup --skip-signup",
                err=True,
            )
            sys.exit(1)
        click.echo("  OTP sent. Check your inbox (expires in ~10 min).")
        otp = click.prompt("OTP code")
        try:
            verify = api.verify_signup(human_email=human_email, otp=otp)
        except RuntimeError as e:
            click.echo(f"  verify failed: {e}", err=True)
            sys.exit(1)
        if "api_key" not in verify:
            click.echo(f"  verify response missing api_key: {verify}", err=True)
            sys.exit(1)
        bashrc_set(AGENTMAIL_API_KEY_ENV, verify["api_key"])
        click.echo(f"  api key persisted to ~/.bashrc as {AGENTMAIL_API_KEY_ENV}")

    # 2. inbox creation
    click.echo(f"\ncreating inbox for username '{username}'...")
    try:
        inbox = api.create_inbox(
            username=username,
            display_name=agent_name(),
            client_id=f"vesta-{agent_name()}",
        )
    except RuntimeError as e:
        click.echo(f"  inbox create failed: {e}", err=True)
        sys.exit(1)
    if "inbox_id" not in inbox or "email_address" not in inbox:
        click.echo(f"  unexpected inbox response: {inbox}", err=True)
        sys.exit(1)
    click.echo(f"  inbox: {inbox['email_address']} (id {inbox['inbox_id']})")

    # 3. webhook registration
    webhook_url_base = _resolve_webhook_url()
    if not webhook_url_base:
        click.echo(
            "error: could not resolve VESTAD_TUNNEL. Set $VESTAD_TUNNEL or run setup from inside the agent container.",
            err=True,
        )
        sys.exit(1)
    secret = webhook_secret()
    if not secret:
        secret = secrets.token_urlsafe(32)
        bashrc_set(AGENTMAIL_WEBHOOK_SECRET_ENV, secret)
    webhook_url = f"{webhook_url_base}/webhook?secret={secret}"
    click.echo(f"\nregistering webhook: {webhook_url}")
    try:
        wh = api.register_webhook(url=webhook_url, event_types=["message.received"])
    except RuntimeError as e:
        click.echo(
            f"  webhook register failed: {e}\n"
            f"  Inbound mail won't reach the agent until this is fixed. "
            f"Configure manually in the AgentMail console with URL: {webhook_url}",
            err=True,
        )
        wh = {}

    # 4. persist config
    cfg = load_config()
    webhook_id = wh["webhook_id"] if wh and "webhook_id" in wh else None
    cfg.update(
        {
            "inbox_id": inbox["inbox_id"],
            "email_address": inbox["email_address"],
            "username": username,
            "webhook_url": webhook_url,
            "webhook_id": webhook_id,
        }
    )
    save_config(cfg)

    click.echo("\nsetup complete.")
    click.echo(f"  address: {inbox['email_address']}")
    click.echo(f"  inbox:   {inbox['inbox_id']}")
    click.echo(f"  webhook: {webhook_url}")
    click.echo("\nnext: register and start the local service")
    click.echo(
        "  PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services "
        "-H \"X-Agent-Token: $AGENT_TOKEN\" -H 'Content-Type: application/json' "
        '-d \'{"name":"agentmail","public":true}\' | '
        "python3 -c \"import sys,json; print(json.load(sys.stdin)['port'])\")"
    )
    click.echo("  screen -dmS agentmail agentmail serve --port $PORT")
