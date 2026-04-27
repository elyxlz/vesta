"""cloudflare-email setup: interactive setup. Prompts for the API token,
verifies it, picks domain + address, enables email routing, deploys the
inbound Worker, generates a worker secret, and persists everything to
~/.bashrc + ~/.cloudflare-email/config.json."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path

import click

from cloudflare_email import cf_api
from cloudflare_email.config import (
    CF_API_TOKEN_ENV,
    CF_WORKER_SECRET_ENV,
    agent_name,
    bashrc_set,
    load_config,
    save_config,
)


WORKER_DIR = Path(__file__).resolve().parents[3] / "worker"


@click.command("setup")
@click.option("--domain", default=None, help="Skip domain prompt, use this domain")
@click.option("--local", default=None, help="Skip local-part prompt, use this local-part")
@click.option("--worker-name", default=None, help="Worker name (default: cloudflare-email-<agent>)")
def setup_cmd(domain: str | None, local: str | None, worker_name: str | None) -> None:
    """Interactive setup. Run once."""
    click.echo("cloudflare-email setup")
    click.echo("=" * 40)

    # 1. ensure API token is in env (and ~/.bashrc for persistence across restarts)
    if not os.environ.get(CF_API_TOKEN_ENV, "").strip():
        click.echo(
            f"\n{CF_API_TOKEN_ENV} is not set. Create a Cloudflare API token with:\n"
            "  Account: Email:Edit, Workers Scripts:Edit\n"
            "  Zone: Email Routing:Edit, DNS:Edit\n"
            "(scope to the email domain only)\n"
        )
        token = click.prompt("paste the API token", hide_input=True)
        bashrc_set(CF_API_TOKEN_ENV, token.strip())

    click.echo("verifying API token...")
    try:
        verify = cf_api.verify_token()
        click.echo(f"  token ok, status={verify['status']}")
    except Exception as e:
        click.echo(f"  token verify failed: {e}", err=True)
        sys.exit(1)

    # 2. pick domain
    zones = cf_api.list_zones()
    if not zones:
        click.echo("error: no zones on this CF account", err=True)
        sys.exit(1)
    if not domain:
        zone_names = [z.name for z in zones]
        click.echo("\navailable domains:")
        for i, n in enumerate(zone_names):
            click.echo(f"  [{i}] {n}")
        default_idx = next((i for i, n in enumerate(zone_names) if n == "vesta.run"), 0)
        idx = click.prompt("pick a domain index", default=default_idx, type=int)
        domain = zone_names[idx]
    zone = next((z for z in zones if z.name == domain), None)
    if not zone:
        click.echo(f"error: domain {domain} not found on account", err=True)
        sys.exit(1)
    zone_id = zone.id
    account_id = zone.account.id

    # 3. pick local-part
    if not local:
        default_local = agent_name().lower()
        local = click.prompt("local-part for the agent's address", default=default_local)
    address = f"{local}@{domain}"
    click.echo(f"\nagent address will be: {address}")

    # 4. enable email routing (inbound) and email sending (outbound) on the domain
    click.echo("enabling Email Routing on the zone...")
    try:
        cf_api.enable_email_routing(zone_id)
        click.echo("  ok")
    except Exception as e:
        click.echo(f"  warn: {e}")

    env = os.environ.copy()
    env["CLOUDFLARE_API_TOKEN"] = cf_api.cf_api_token()
    env["CLOUDFLARE_ACCOUNT_ID"] = account_id

    # Pre-flight: skip enable if already onboarded.
    click.echo("checking Email Sending status...")
    already_enabled = False
    try:
        proc = subprocess.run(
            ["wrangler", "email", "sending", "list"],
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        listed_tokens = {tok.strip(".,\"' ") for line in proc.stdout.splitlines() for tok in line.split()}
        already_enabled = domain in listed_tokens
    except FileNotFoundError:
        click.echo(
            "error: wrangler not installed. Run `npm i -g wrangler` then re-run setup.",
            err=True,
        )
        sys.exit(1)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        click.echo(f"  warn: could not list (will attempt enable anyway): {e}")

    if already_enabled:
        click.echo(f"  Email Sending already enabled on {domain}")
    else:
        click.echo("enabling Email Sending on the domain (outbound)...")
        try:
            subprocess.run(
                ["wrangler", "email", "sending", "enable", domain],
                env=env,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            click.echo(
                f"  outbound onboarding failed: {e}\n"
                f"  `cloudflare-email send` will not work until this is resolved.\n"
                f"  Check the API token has Account:Email:Edit and Zone:DNS:Edit on {domain}.",
                err=True,
            )
            sys.exit(1)

    click.echo(f"DNS records required for outbound on {domain}:")
    subprocess.run(
        ["wrangler", "email", "sending", "dns", "get", domain],
        env=env,
        check=False,
    )

    # 5. ensure worker secret exists (generate + persist to ~/.bashrc on first run)
    secret = os.environ.get(CF_WORKER_SECRET_ENV, "").strip()
    if not secret:
        secret = secrets.token_urlsafe(32)
        bashrc_set(CF_WORKER_SECRET_ENV, secret)

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

    # postal-mime is bundled at deploy time — install worker deps first.
    click.echo("installing worker dependencies...")
    try:
        subprocess.run(["npm", "install"], cwd=str(WORKER_DIR), env=env, check=True)
    except FileNotFoundError:
        click.echo("error: npm not found. Install Node.js then re-run setup.", err=True)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        click.echo(f"  npm install failed: {e}", err=True)
        sys.exit(1)

    try:
        subprocess.run(
            [
                "wrangler",
                "deploy",
                "--name",
                worker_name,
                "--var",
                f"INBOUND_URL:{inbound_url}",
            ],
            cwd=str(WORKER_DIR),
            env=env,
            check=True,
        )
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

    # 7. routing rules — list once, surface address conflicts, then upsert.
    # A conflict means another rule (a stale one, or another agent on the same
    # domain) already routes the address we're about to claim. Setup never
    # deletes a foreign rule — that would silently break another agent's
    # inbound. The only safe options are change-and-retry or abort.
    click.echo("creating routing rules...")
    while True:
        rules = cf_api.list_routing_rules(zone_id)
        # Probe the two address shapes our rules will own. find_address_conflicts
        # treats existing matcher values as globs, so `*@domain` and `local*@domain`
        # are caught by the bare probe; `local+*@domain` is caught by the sub probe.
        bare_conflicts = cf_api.find_address_conflicts(rules, address, f"agent-{address}")
        sub_conflicts = cf_api.find_address_conflicts(rules, f"{local}+conflict-probe@{domain}", f"agent-{local}-subaddress")
        # A rule may match both probes (e.g. catch-all); dedupe by tag.
        seen_tags: set[str] = set()
        all_conflicts = []
        for r in bare_conflicts + sub_conflicts:
            if r.tag in seen_tags:
                continue
            seen_tags.add(r.tag)
            all_conflicts.append(r)
        if not all_conflicts:
            break
        click.echo(f"\n⚠ {address} (or its sub-addresses) is already routed:")
        for r in all_conflicts:
            actions = ", ".join(f"{a.type}={a.value}" for a in r.actions)
            click.echo(f"  - rule {r.name!r}: {actions}")
        click.echo(
            "Another agent (or a stale rule) already owns this address. "
            "Pick a different local-part, or abort and remove the rule by hand "
            "in the Cloudflare dashboard if you're sure it's stale."
        )
        choice = click.prompt(
            "what now?",
            type=click.Choice(["change", "abort"]),
            default="abort",
        )
        if choice == "abort":
            click.echo("aborted.")
            sys.exit(2)
        # choice == "change"
        local = click.prompt("new local-part")
        address = f"{local}@{domain}"
        click.echo(f"new address: {address}")

    cf_api.upsert_worker_route_rule(zone_id, address, worker_name, rules=rules)
    cf_api.upsert_subaddress_rule(zone_id, local, domain, worker_name, rules=rules)

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
    bashrc_set("CF_EMAIL_DOMAIN", domain)
    bashrc_set("CF_EMAIL_ADDRESS", address)

    click.echo("\nsetup complete.")
    click.echo(f"  address: {address}")
    click.echo(f"  worker:  {worker_name}")
    click.echo(f"  inbound: {inbound_url}/inbound")
    click.echo("\nnext: register and start the local service")
    click.echo(
        "  PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services "
        "-H \"X-Agent-Token: $AGENT_TOKEN\" -H 'Content-Type: application/json' "
        '-d \'{"name":"cloudflare-email","public":true}\' | '
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
    rules = cf_api.list_routing_rules(cfg["zone_id"])
    cf_api.upsert_worker_route_rule(cfg["zone_id"], cfg["address"], cfg["worker_name"], rules=rules)
    cf_api.upsert_subaddress_rule(cfg["zone_id"], cfg["local"], cfg["domain"], cfg["worker_name"], rules=rules)
    click.echo("ok.")


def _resolve_inbound_url() -> str:
    """Resolve the public URL the Worker should POST inbound mail to.
    Reads VESTAD_TUNNEL from env (set by vestad on container start)."""
    tunnel = os.environ["VESTAD_TUNNEL"].strip() if "VESTAD_TUNNEL" in os.environ else ""
    if not tunnel:
        return ""
    # vestad routes /agents/<name>/<service>/<path> through agent_proxy_handler.
    return f"{tunnel.rstrip('/')}/agents/{agent_name()}/cloudflare-email"
