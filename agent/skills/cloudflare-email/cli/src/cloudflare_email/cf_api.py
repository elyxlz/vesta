"""Thin wrapper around the Cloudflare REST API. Only the endpoints we need."""

from __future__ import annotations

import httpx

from cloudflare_email.config import cf_api_token


BASE = "https://api.cloudflare.com/client/v4"


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=BASE,
        headers={"Authorization": f"Bearer {cf_api_token()}"},
        timeout=30.0,
    )


def verify_token() -> dict:
    with _client() as c:
        r = c.get("/user/tokens/verify")
        r.raise_for_status()
        return r.json()


def list_zones() -> list[dict]:
    with _client() as c:
        r = c.get("/zones", params={"per_page": 50})
        r.raise_for_status()
        return r.json()["result"]


def find_zone(domain: str) -> dict | None:
    for z in list_zones():
        if z["name"] == domain:
            return z
    return None


def get_account_id() -> str:
    zones = list_zones()
    if not zones:
        raise RuntimeError("No zones on this Cloudflare account")
    return zones[0]["account"]["id"]


def enable_email_routing(zone_id: str) -> dict:
    """Enable Email Routing on a zone. Idempotent."""
    with _client() as c:
        r = c.post(f"/zones/{zone_id}/email/routing/enable")
        if r.status_code == 409:
            return c.get(f"/zones/{zone_id}/email/routing").json()["result"]
        r.raise_for_status()
        return r.json()["result"]


def list_routing_rules(zone_id: str) -> list[dict]:
    with _client() as c:
        r = c.get(f"/zones/{zone_id}/email/routing/rules")
        r.raise_for_status()
        return r.json()["result"]


def upsert_worker_route_rule(zone_id: str, address: str, worker_name: str) -> dict:
    """Create or update a routing rule that forwards address (and +sub-addresses) to a Worker."""
    rules = list_routing_rules(zone_id)
    matching = [r for r in rules if r.get("name") == f"agent-{address}"]
    payload = {
        "name": f"agent-{address}",
        "enabled": True,
        "matchers": [
            {"type": "literal", "field": "to", "value": address},
        ],
        "actions": [
            {"type": "worker", "value": [worker_name]},
        ],
        "priority": 0,
    }
    with _client() as c:
        if matching:
            r = c.put(
                f"/zones/{zone_id}/email/routing/rules/{matching[0]['tag']}",
                json=payload,
            )
        else:
            r = c.post(f"/zones/{zone_id}/email/routing/rules", json=payload)
        r.raise_for_status()
        return r.json()["result"]


def upsert_subaddress_rule(zone_id: str, local: str, domain: str, worker_name: str) -> dict:
    """Catch-all rule for `local+*@domain` -> Worker."""
    rules = list_routing_rules(zone_id)
    rule_name = f"agent-{local}-subaddress"
    matching = [r for r in rules if r.get("name") == rule_name]
    payload = {
        "name": rule_name,
        "enabled": True,
        "matchers": [
            {
                "type": "regex",
                "field": "to",
                "value": f"^{local}\\+.*@{domain.replace('.', '\\\\.')}$",
            },
        ],
        "actions": [
            {"type": "worker", "value": [worker_name]},
        ],
        "priority": 1,
    }
    with _client() as c:
        if matching:
            r = c.put(
                f"/zones/{zone_id}/email/routing/rules/{matching[0]['tag']}",
                json=payload,
            )
        else:
            r = c.post(f"/zones/{zone_id}/email/routing/rules", json=payload)
        r.raise_for_status()
        return r.json()["result"]


def send_email(account_id: str, *, from_addr: str, to_addr: str, subject: str, body_text: str, body_html: str | None = None, reply_to: str | None = None) -> dict:
    """Send via the Email Sending API."""
    payload = {
        "from": {"email": from_addr},
        "to": [{"email": to_addr}],
        "subject": subject,
        "text": body_text,
    }
    if body_html:
        payload["html"] = body_html
    if reply_to:
        payload["headers"] = {"In-Reply-To": reply_to, "References": reply_to}
    with _client() as c:
        r = c.post(f"/accounts/{account_id}/email/sending/send", json=payload)
        r.raise_for_status()
        return r.json()
