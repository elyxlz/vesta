"""cloudflare-email setup: interactive setup. Verifies the API token, picks
domain + address, enables email routing, deploys the inbound Worker, and stashes
the worker secret in keeper."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path

import click

from cloudflare_email import cf_api
from cloudflare_email.config import (
    agent_name,
    keeper_get,
    keeper_store,
    load_config,
    save_config,
)


WORKER_DIR = Path(__file__).resolve().parents[3] / "worker"


def _bashrc_set(key: str, value: str) -> None:
    """Persist KEY=VALUE in ~/.bashrc, replacing any prior export."""
    bashrc = Path.home() / ".bashrc"
    text = bashrc.read_text() if bashrc.exists() else ""
    lines = [l for l in text.splitlines() if not l.startswith(f"export {key}=")]
    lines.append(f"export {key}={value}")
    bashrc.write_text("\n".join(lines) + "\n")


@click.command("setup")
@click.option("--domain", default=None, help="Skip domain prompt, use this domain")
@click.option("--local", default=None, help="Skip local-part prompt, use this local-part")
@click.option("--worker-name", default=None, help="Worker name (default: cloudflare-email-<agent>)")
def setup_cmd(domain: str | None, local: str | None, worker_name: str | None) -> None:
    """Interactive setup. Run once."""
    click.echo("cloudflare-email setup")
    click.echo("=" * 40)

    # 1. verify token
    click.echo("verifying API token...")
    if not keeper_get("cloudflare/api-token"):
        click.echo("\nNo Cloudflare API token in keeper. Create one in CF dashboard with:")
        click.echo("  Account: Email:Edit, Workers Scripts:Edit")
        click.echo("  Zone: Email Routing:Edit, DNS:Edit")
        click.echo("Then: keeper store cloudflare/api-token '<token>'")
        sys.exit(2)
    try:
        verify = cf_api.verify_token()
        click.echo(f"  token ok, status={verify['result'].get('status')}")
    except Exception as e:
        click.echo(f"  token verify failed: {e}", err=True)
        sys.exit(1)

    # 2. pick domain
    zones = cf_api.list_zones()
    if not zones:
        click.echo("error: no zones on this CF account", err=True)
        sys.exit(1)
    if not domain:
        zone_names = [z["name"] for z in zones]
        click.echo("\navailable domains:")
        for i, n in enumerate(zone_names):
            click.echo(f"  [{i}] {n}")
        default_idx = next((i for i, n in enumerate(zone_names) if n == "vesta.run"), 0)
        idx = click.prompt("pick a domain index", default=default_idx, type=int)
        domain = zone_names[idx]
    zone = next((z for z in zones if z["name"] == domain), None)
    if not zone:
        click.echo(f"error: domain {domain} not found on account", err=True)
        sys.exit(1)
    zone_id = zone["id"]
    account_id = zone["account"]["id"]

    # 3. pick local-part
    if not local:
        default_local = agent_name().lower()
        local = click.prompt("local-part for the agent's address", default=default_local)
    address = f"{local}@{domain}"
    click.echo(f"\nagent address will be: {address}")

    # 4. enable email routing
    click.echo("enabling Email Routing on the zone...")
    try:
        cf_api.enable_email_routing(zone_id)
        click.echo("  ok")
    except Exception as e:
        click.echo(f"  warn: {e}")

    # 5. ensure worker secret exists
    secret = keeper_get("cloudflare-email/worker-secret")
    if not secret:
        secret = secrets.token_urlsafe(32)
        if not keeper_store("cloudflare-email/worker-secret", secret):
            click.echo("warn: failed to write worker secret to keeper, holding in memory only")

    # 6. deploy worker
    if not worker_name:
        worker_name = f"cloudflare-email-{agent_name().lower()}"
    click.echo(f"deploying Worker `{worker_name}`...")
    if not WORKER_DIR.exists():
        click.echo(f"error: worker dir missing: {WORKER_DIR}", err=True)
        sys.exit(1)
    inbound_url = _resolve_inbound_url()
    if not inbound_url:
        click.echo(
            "error: could not resolve VESTAD_TUNNEL. Set $VESTAD_TUNNEL or run setup from inside the agent container.",
            err=True,
        )
        sys.exit(1)
    env = os.environ.copy()
    env["CLOUDFLARE_API_TOKEN"] = cf_api.cf_api_token()
    env["CLOUDFLARE_ACCOUNT_ID"] = account_id
    # write env-specific wrangler vars
    (WORKER_DIR / ".env").write_text(
        f"INBOUND_URL={inbound_url}\nWORKER_SECRET={secret}\n"
    )
    try:
        subprocess.run(
            ["wrangler", "deploy", "--name", worker_name],
            cwd=str(WORKER_DIR),
            env=env,
            check=True,
        )
    except FileNotFoundError:
        click.echo(
            "error: wrangler not installed. Run `npm i -g wrangler` then re-run setup.",
            err=True,
        )
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        click.echo(f"  wrangler deploy failed: {e}", err=True)
        sys.exit(1)
    # set worker secret on the deployed Worker
    subprocess.run(
        ["wrangler", "secret", "put", "WORKER_SECRET", "--name", worker_name],
        input=secret,
        text=True,
        cwd=str(WORKER_DIR),
        env=env,
        check=False,
    )

    # 7. routing rules
    click.echo("creating routing rules...")
    cf_api.upsert_worker_route_rule(zone_id, address, worker_name)
    cf_api.upsert_subaddress_rule(zone_id, local, domain, worker_name)

    # 8. persist config
    cfg = load_config()
    cfg.update(
        {
            "domain": domain,
            "zone_id": zone_id,
            "account_id": account_id,
            "address": address,
            "local": local,
            "worker_name": worker_name,
            "inbound_url": inbound_url,
        }
    )
    save_config(cfg)
    _bashrc_set("CF_EMAIL_DOMAIN", domain)
    _bashrc_set("CF_EMAIL_ADDRESS", address)

    click.echo("\nsetup complete.")
    click.echo(f"  address: {address}")
    click.echo(f"  worker:  {worker_name}")
    click.echo(f"  inbound: {inbound_url}/inbound")
    click.echo("\nnext: register and start the local service")
    click.echo(
        "  PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services "
        "-H \"X-Agent-Token: $AGENT_TOKEN\" -H 'Content-Type: application/json' "
        "-d '{\"name\":\"cloudflare-email\",\"public\":true}' | "
        "python3 -c \"import sys,json; print(json.load(sys.stdin)['port'])\")"
    )
    click.echo("  screen -dmS cloudflare-email cloudflare-email serve --port $PORT")


@click.command("reconcile")
def reconcile_cmd() -> None:
    """Re-verify routing + Worker + secret without prompting."""
    cfg = load_config()
    if not cfg.get("domain"):
        click.echo("not yet configured. Run `cloudflare-email setup`", err=True)
        sys.exit(2)
    click.echo("verifying token...")
    cf_api.verify_token()
    click.echo("checking zone...")
    cf_api.find_zone(cfg["domain"])
    click.echo("re-applying routing rules...")
    cf_api.upsert_worker_route_rule(cfg["zone_id"], cfg["address"], cfg["worker_name"])
    cf_api.upsert_subaddress_rule(
        cfg["zone_id"], cfg["local"], cfg["domain"], cfg["worker_name"]
    )
    click.echo("ok.")


def _resolve_inbound_url() -> str:
    """Resolve the public URL the Worker should POST inbound mail to.
    Reads VESTAD_TUNNEL from env (set by vestad on container start)."""
    tunnel = os.environ.get("VESTAD_TUNNEL", "").strip()
    if not tunnel:
        return ""
    # vestad routes /agents/<name>/services/<name>/<path>
    return f"{tunnel.rstrip('/')}/agents/{agent_name()}/services/cloudflare-email"
