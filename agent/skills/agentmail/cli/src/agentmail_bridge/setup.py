"""agentmail setup: autonomous sign-up via disposable mail, inbox + webhook
provisioning via the official AgentMail Python SDK, and a local install of
the official npm CLI for passthrough.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys

import click
from agentmail import AgentMail

from agentmail_bridge import disposable_mail
from agentmail_bridge.config import (
    AGENTMAIL_API_KEY_ENV,
    AGENTMAIL_WEBHOOK_SECRET_ENV,
    CONFIG_DIR,
    NPM_CLI_BIN,
    agent_name,
    bashrc_set,
    load_config,
    save_config,
    webhook_secret,
)


def _resolve_webhook_url() -> str:
    """Public URL AgentMail POSTs inbound mail to. Reads VESTAD_TUNNEL from env."""
    tunnel = os.environ["VESTAD_TUNNEL"].strip() if "VESTAD_TUNNEL" in os.environ else ""
    if not tunnel:
        return ""
    return f"{tunnel.rstrip('/')}/agents/{agent_name()}/agentmail"


def _install_npm_cli() -> None:
    """Install agentmail-cli locally to ~/.agentmail/node_modules/. Idempotent.

    Local (not -g) so our Python `agentmail` binary stays the only one on
    PATH; the wrapper passes unknown commands to NPM_CLI_BIN by full path.
    """
    if NPM_CLI_BIN.exists():
        click.echo("  agentmail-cli already installed")
        return
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    click.echo("installing agentmail-cli to ~/.agentmail/...")
    try:
        subprocess.run(
            ["npm", "install", "--prefix", str(CONFIG_DIR), "agentmail-cli"],
            check=True,
        )
    except FileNotFoundError:
        click.echo("error: npm not found. Install Node.js then re-run setup.", err=True)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        click.echo(f"  npm install failed: {e}", err=True)
        sys.exit(1)
    if not NPM_CLI_BIN.exists():
        click.echo(f"  warn: expected binary at {NPM_CLI_BIN} but didn't find it", err=True)


def _autonomous_signup(username: str) -> dict:
    """Sign up to AgentMail using a disposable mail.tm inbox for the OTP.

    Returns dict with keys: api_key, inbox_id, organization_id, email_address.
    Raises RuntimeError if any step fails.
    """
    click.echo("creating disposable inbox for OTP delivery...")
    dispo = disposable_mail.create_account()
    click.echo(f"  using {dispo['email']}")

    click.echo("requesting AgentMail sign-up...")
    bootstrap_client = AgentMail(api_key="bootstrap")
    signup = bootstrap_client.agent.sign_up(human_email=dispo["email"], username=username)

    click.echo("polling disposable inbox for OTP (up to 3 min)...")
    msg = disposable_mail.wait_for_message(dispo["token"], sender_contains="agentmail")
    otp = disposable_mail.extract_otp(msg)
    click.echo(f"  got OTP: {otp}")

    click.echo("verifying OTP...")
    verified_client = AgentMail(api_key=signup.api_key)
    verified_client.agent.verify(otp_code=otp)

    return {
        "api_key": signup.api_key,
        "inbox_id": signup.inbox_id,
        "organization_id": signup.organization_id,
        "email_address": f"{username}@agentmail.to",
    }


def _prompt_signup(username: str) -> dict:
    """Manual sign-up: ask for an email, then the OTP that arrives there."""
    human_email = click.prompt("your email (where AgentMail will send the OTP)")
    bootstrap_client = AgentMail(api_key="bootstrap")
    signup = bootstrap_client.agent.sign_up(human_email=human_email, username=username)
    click.echo("  OTP sent. Check your inbox (expires in ~10 min).")
    otp = click.prompt("OTP code")
    verified_client = AgentMail(api_key=signup.api_key)
    verified_client.agent.verify(otp_code=otp)
    return {
        "api_key": signup.api_key,
        "inbox_id": signup.inbox_id,
        "organization_id": signup.organization_id,
        "email_address": f"{username}@agentmail.to",
    }


def _create_inbox_for_existing_account(username: str) -> dict:
    """--skip-signup path: caller already set AGENTMAIL_API_KEY."""
    key = os.environ[AGENTMAIL_API_KEY_ENV].strip()
    client = AgentMail(api_key=key)
    inbox = client.inboxes.create(
        username=username,
        display_name=agent_name(),
        client_id=f"vesta-{agent_name()}",
    )
    return {
        "api_key": key,
        "inbox_id": inbox.inbox_id,
        "email_address": inbox.email_address,
    }


@click.command("setup")
@click.option(
    "--username",
    default=None,
    help="Local-part for the agent's address (default: $AGENT_NAME lowercased)",
)
@click.option(
    "--prompt",
    "use_prompt",
    is_flag=True,
    help="Skip autonomous mode; ask the user for an email + OTP",
)
@click.option(
    "--skip-signup",
    is_flag=True,
    help="Skip sign-up; assume AGENTMAIL_API_KEY is already set",
)
def setup_cmd(username: str | None, use_prompt: bool, skip_signup: bool) -> None:
    """Set up AgentMail for the agent. Autonomous by default."""
    click.echo("agentmail setup")
    click.echo("=" * 40)

    if not username:
        username = agent_name().lower()

    have_key = bool(os.environ.get(AGENTMAIL_API_KEY_ENV, "").strip())

    if skip_signup or have_key:
        if not have_key:
            click.echo(
                f"--skip-signup passed but {AGENTMAIL_API_KEY_ENV} is empty.\n"
                f"  Sign up at https://console.agentmail.to (or via the browser "
                f"skill), set the key in ~/.bashrc, then re-run.",
                err=True,
            )
            sys.exit(2)
        click.echo(f"{AGENTMAIL_API_KEY_ENV} already set; creating inbox without sign-up.")
        try:
            inbox = _create_inbox_for_existing_account(username)
        except Exception as e:
            click.echo(f"  inbox create failed: {e}", err=True)
            sys.exit(1)
    elif use_prompt:
        click.echo("\nmanual sign-up (--prompt):")
        try:
            inbox = _prompt_signup(username)
        except Exception as e:
            click.echo(f"  sign-up failed: {e}", err=True)
            sys.exit(1)
        bashrc_set(AGENTMAIL_API_KEY_ENV, inbox["api_key"])
    else:
        click.echo("\nautonomous sign-up:")
        try:
            inbox = _autonomous_signup(username)
        except Exception as e:
            click.echo(
                f"\n  autonomous sign-up failed: {e}\n"
                f"  Likely causes: mail.tm is down, AgentMail rejected the disposable\n"
                f"  domain, or the OTP didn't arrive within the timeout.\n"
                f"  Recovery: `agentmail setup --prompt` (manual), or browser-sign-up\n"
                f"  + `agentmail setup --skip-signup`.",
                err=True,
            )
            sys.exit(1)
        bashrc_set(AGENTMAIL_API_KEY_ENV, inbox["api_key"])

    click.echo(f"  inbox: {inbox['email_address']} (id {inbox['inbox_id']})")

    # Set the inbox display_name to the agent name. AgentMail's sign-up path
    # creates inboxes with display_name="AgentMail" by default, so without this
    # the From header on outbound mail reads "AgentMail <user@agentmail.to>"
    # instead of "athena <user@agentmail.to>". The skip-signup path already
    # passes display_name on inbox create; this covers the autonomous and
    # --prompt paths where the inbox is auto-created on sign_up.
    try:
        AgentMail(api_key=inbox["api_key"]).inboxes.update(
            inbox_id=inbox["inbox_id"],
            display_name=agent_name(),
        )
        click.echo(f"  display_name: {agent_name()}")
    except Exception as e:
        click.echo(f"  warn: display_name update failed (outbound From header will read 'AgentMail'): {e}")

    # Install the npm CLI for passthrough before the webhook step so that even
    # a partial setup (e.g. webhook fails because VESTAD_TUNNEL isn't set yet)
    # leaves the agent able to use `agentmail inboxes:messages send` etc.
    click.echo("")
    _install_npm_cli()

    # Webhook registration via SDK
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
    client = AgentMail(api_key=inbox["api_key"])
    webhook_id: str | None = None
    try:
        wh = client.webhooks.create(url=webhook_url, event_types=["message.received"])
        webhook_id = wh.webhook_id
    except Exception as e:
        click.echo(
            f"  webhook register failed: {e}\n"
            f"  Inbound mail won't reach the agent until this is fixed. "
            f"Configure manually with URL: {webhook_url}",
            err=True,
        )

    # Persist config
    cfg = load_config()
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
    click.echo(f"  npm cli: {NPM_CLI_BIN}")
    click.echo("\nfor send / list / etc., the wrapper passes through to the official CLI:")
    click.echo(f"  agentmail inboxes:messages send --inbox-id {inbox['inbox_id']} \\")
    click.echo("    --to recipient@example.com --subject 'hi' --text 'hello'")
    click.echo("\nnext: register and start the local webhook receiver")
    click.echo(
        "  PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services "
        "-H \"X-Agent-Token: $AGENT_TOKEN\" -H 'Content-Type: application/json' "
        '-d \'{"name":"agentmail","public":true}\' | '
        "python3 -c \"import sys,json; print(json.load(sys.stdin)['port'])\")"
    )
    click.echo("  screen -dmS agentmail agentmail serve --port $PORT")
