"""agentmail setup: autonomous sign-up via disposable mail, inbox creation,
webhook registration. No user input on the happy path.
"""

from __future__ import annotations

import os
import secrets
import sys

import click

from agentmail import api, disposable_mail
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


def _autonomous_signup(username: str) -> str:
    """Run the full sign-up flow without any user input.

    Creates a disposable mail.tm inbox, signs up to AgentMail with it, polls
    for the OTP, verifies. Returns the AgentMail API key. Raises RuntimeError
    on any step failure (caller can decide whether to fall back).
    """
    click.echo("creating disposable inbox for OTP delivery...")
    dispo = disposable_mail.create_account()
    click.echo(f"  using {dispo['email']}")

    click.echo("requesting AgentMail sign-up...")
    api.sign_up(human_email=dispo["email"], username=username)

    click.echo("polling disposable inbox for OTP (up to 3 min)...")
    msg = disposable_mail.wait_for_message(dispo["token"], sender_contains="agentmail")
    otp = disposable_mail.extract_otp(msg)
    click.echo(f"  got OTP: {otp}")

    click.echo("verifying OTP...")
    verify = api.verify_signup(human_email=dispo["email"], otp=otp)
    if "api_key" not in verify:
        raise RuntimeError(f"verify response missing api_key: {verify}")
    return verify["api_key"]


def _prompt_signup(username: str) -> str:
    """Manual sign-up: ask the user for an email, then for the OTP they receive."""
    human_email = click.prompt("your email (where AgentMail will send the OTP)")
    api.sign_up(human_email=human_email, username=username)
    click.echo("  OTP sent. Check your inbox (expires in ~10 min).")
    otp = click.prompt("OTP code")
    verify = api.verify_signup(human_email=human_email, otp=otp)
    if "api_key" not in verify:
        raise RuntimeError(f"verify response missing api_key: {verify}")
    return verify["api_key"]


@click.command("setup")
@click.option("--username", default=None, help="Local-part for the agent's address (default: $AGENT_NAME lowercased)")
@click.option("--prompt", "use_prompt", is_flag=True, help="Skip autonomous mode; ask the user for an email + OTP")
@click.option("--skip-signup", is_flag=True, help="Skip sign-up entirely; assume AGENTMAIL_API_KEY is already set")
def setup_cmd(username: str | None, use_prompt: bool, skip_signup: bool) -> None:
    """Set up AgentMail for the agent. Autonomous by default."""
    click.echo("agentmail setup")
    click.echo("=" * 40)

    if not username:
        username = agent_name().lower()

    have_key = bool(os.environ.get(AGENTMAIL_API_KEY_ENV, "").strip())

    if skip_signup or have_key:
        if have_key:
            click.echo(f"{AGENTMAIL_API_KEY_ENV} already set; skipping sign-up.")
        else:
            click.echo(
                f"--skip-signup passed but {AGENTMAIL_API_KEY_ENV} is empty.\n"
                f"  Set it (e.g. via the browser skill on https://console.agentmail.to) "
                f"and re-run.",
                err=True,
            )
            sys.exit(2)
    elif use_prompt:
        click.echo("\nmanual sign-up (--prompt):")
        try:
            api_key = _prompt_signup(username)
        except Exception as e:
            click.echo(f"  sign-up failed: {e}", err=True)
            sys.exit(1)
        bashrc_set(AGENTMAIL_API_KEY_ENV, api_key)
        click.echo(f"  api key persisted to ~/.bashrc as {AGENTMAIL_API_KEY_ENV}")
    else:
        click.echo("\nautonomous sign-up:")
        try:
            api_key = _autonomous_signup(username)
        except Exception as e:
            click.echo(
                f"\n  autonomous sign-up failed: {e}\n"
                f"  This usually means one of:\n"
                f"    - mail.tm (disposable mail provider) is down or rate-limiting\n"
                f"    - AgentMail's anti-fraud rejected the disposable domain\n"
                f"    - The OTP didn't arrive within the timeout\n"
                f"  Retry with `agentmail setup --prompt` to do it manually,\n"
                f"  or sign up via the browser skill at https://console.agentmail.to,\n"
                f"  set AGENTMAIL_API_KEY in ~/.bashrc, and run `agentmail setup --skip-signup`.",
                err=True,
            )
            sys.exit(1)
        bashrc_set(AGENTMAIL_API_KEY_ENV, api_key)
        click.echo(f"  api key persisted to ~/.bashrc as {AGENTMAIL_API_KEY_ENV}")

    # Inbox creation
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

    # Webhook registration
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

    # Persist config
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
