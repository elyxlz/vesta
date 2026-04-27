"""cloudflare-email subscribe: subscribe to a newsletter using the agent's address.

Logs the subscription so the agent can track sources and unsubscribe later.
Confirmation-link auto-clicking is best-effort: it watches inbound mail for ~5
minutes after signup, parses confirmation URLs out of typical newsletter
templates, and visits them with httpx. Many providers require JavaScript or
bot-protection challenges that this won't handle. For those, the user can click
the link from the inbound notification manually.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import click
import httpx

from cloudflare_email.config import (
    NOTIFICATIONS_DIR,
    email_address,
    load_config,
)


SUBS_LOG = Path.home() / ".cloudflare-email" / "subscriptions.json"
CONFIRM_PATTERNS = [
    re.compile(r'href="(https?://[^"]*(?:confirm|verify|activate|subscribe)[^"]*)"', re.I),
    re.compile(r'(https?://[^\s<>"]*(?:confirm|verify|activate|subscribe)[^\s<>"]*)', re.I),
]


def _log_subscription(url: str, source_local: str, address: str) -> None:
    SUBS_LOG.parent.mkdir(parents=True, exist_ok=True)
    subs = []
    if SUBS_LOG.exists():
        try:
            subs = json.loads(SUBS_LOG.read_text())
        except json.JSONDecodeError:
            subs = []
    subs.append(
        {
            "signup_url": url,
            "source_local": source_local,
            "address": address,
            "subscribed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    SUBS_LOG.write_text(json.dumps(subs, indent=2))


def _watch_for_confirmation(source_local: str, timeout: int = 300) -> str | None:
    """Watch the notifications dir for a confirmation email matching source_local."""
    deadline = time.time() + timeout
    seen: set[str] = set()
    while time.time() < deadline:
        for path in NOTIFICATIONS_DIR.glob("*-cloudflare-email-message.json"):
            if path.name in seen:
                continue
            seen.add(path.name)
            try:
                payload = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            if source_local not in payload.get("to", "").lower():
                continue
            body = (payload.get("body_html") or "") + "\n" + (payload.get("body_text") or "")
            for pat in CONFIRM_PATTERNS:
                m = pat.search(body)
                if m:
                    return m.group(1)
        time.sleep(5)
    return None


@click.command("subscribe")
@click.option("--url", "signup_url", required=True, help="Newsletter signup form URL or POST endpoint")
@click.option("--source", default=None, help="Sub-address tag (default: parsed from URL host)")
@click.option("--no-watch", is_flag=True, help="Don't wait for confirmation email")
def subscribe_cmd(signup_url: str, source: str | None, no_watch: bool) -> None:
    cfg = load_config()
    if not cfg.get("address"):
        click.echo("error: skill not configured. Run `cloudflare-email setup` first", err=True)
        sys.exit(2)
    base_local = cfg.get("local", email_address().split("@")[0])
    if not source:
        host = httpx.URL(signup_url).host
        source = host.replace(".", "-")[:32] if host else "newsletter"
    sub_addr = f"{base_local}+{source}@{cfg['domain']}"
    click.echo(f"subscribing {sub_addr} via {signup_url}")
    try:
        r = httpx.post(signup_url, data={"email": sub_addr}, follow_redirects=True, timeout=30.0)
        click.echo(f"  signup status: {r.status_code}")
    except Exception as e:
        click.echo(f"  signup request failed: {e}", err=True)
        sys.exit(1)

    _log_subscription(signup_url, source, sub_addr)

    if no_watch:
        return
    click.echo("watching for confirmation email (up to 5 min)...")
    confirm_url = _watch_for_confirmation(source)
    if not confirm_url:
        click.echo("  no confirmation email seen yet. Check notifications later.")
        return
    click.echo(f"  found confirm url: {confirm_url}")
    try:
        cr = httpx.get(confirm_url, follow_redirects=True, timeout=30.0)
        click.echo(f"  confirmation visited, status {cr.status_code}")
    except Exception as e:
        click.echo(f"  confirmation visit failed: {e}", err=True)
