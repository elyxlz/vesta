"""Thin wrapper over the official Cloudflare Python SDK.

Outbound send still hits the REST endpoint directly — `email_service.send` is
not exposed by `cloudflare` v4.3.1. Drop this shim once the SDK catches up.
"""

from __future__ import annotations

import fnmatch
import json
from typing import Any

import httpx
from cloudflare import Cloudflare
from cloudflare.types.email_routing import EmailRoutingRule

from cloudflare_email.config import cf_api_token


SEND_BASE_URL = "https://api.cloudflare.com/client/v4"

# Avoid re-shelling to keeper for every SDK call. The token only rotates via
# `keeper store ... && cloudflare-email reconcile`, and reconcile runs in a
# fresh process — no stale-cache concern.
_cached_token: str | None = None


def _resolve_token() -> str:
    global _cached_token
    if _cached_token is None:
        _cached_token = cf_api_token()
    return _cached_token


def _client() -> Cloudflare:
    return Cloudflare(api_token=_resolve_token())


def verify_token() -> dict:
    return _client().user.tokens.verify().model_dump()


def list_zones() -> list:
    return list(_client().zones.list())


def find_zone(domain: str):
    for z in _client().zones.list(name=domain):
        if z.name == domain:
            return z
    return None


def get_account_id() -> str:
    zones = list_zones()
    if not zones:
        raise RuntimeError("No zones on this Cloudflare account")
    return zones[0].account.id


def enable_email_routing(zone_id: str):
    """Enable Email Routing on a zone. Idempotent — already-enabled returns settings."""
    return _client().email_routing.enable(zone_id=zone_id, body={})


def list_routing_rules(zone_id: str) -> list[EmailRoutingRule]:
    return list(_client().email_routing.rules.list(zone_id=zone_id))


def _find_rule_by_name(rules: list[EmailRoutingRule], name: str) -> EmailRoutingRule | None:
    for r in rules:
        if r.name == name:
            return r
    return None


def find_address_conflicts(
    rules: list[EmailRoutingRule], address: str, our_rule_name: str
) -> list[EmailRoutingRule]:
    """Return enabled rules whose matchers would intercept `address`.

    `address` must be a concrete address (no wildcards) — the function
    treats every existing rule's matcher value as a glob pattern and
    asks whether `address` falls inside it. This covers:

    - `type="all"` rules (catch-all on the zone — eats every address).
    - `type="literal", field="to"` rules whose value is an exact match.
    - The same with CF wildcard literals (`*@domain`, `local*@domain`,
      `local+*@domain`) — a `*` in the matcher value is treated as the
      glob CF treats it as.

    Skips rules named `our_rule_name` (those are ours to upsert) and
    disabled rules (they don't route).

    To probe both the bare address and the sub-address namespace, call
    twice with two concrete probes (e.g. `local@domain` and
    `local+probe@domain`).
    """
    addr = address.lower()
    conflicts: list[EmailRoutingRule] = []
    for r in rules:
        if r.name == our_rule_name:
            continue
        if not r.enabled:
            continue
        for m in r.matchers:
            if m.type == "all":
                conflicts.append(r)
                break
            if (
                m.type == "literal"
                and m.field == "to"
                and m.value
                and fnmatch.fnmatchcase(addr, m.value.lower())
            ):
                conflicts.append(r)
                break
    return conflicts


def upsert_worker_route_rule(
    zone_id: str,
    address: str,
    worker_name: str,
    *,
    rule_name: str | None = None,
    priority: int = 0,
    rules: list[EmailRoutingRule] | None = None,
):
    """Create or update a routing rule that forwards `address` to `worker_name`.

    Address may be exact (`agent@example.com`) or a CF wildcard literal
    (`agent+*@example.com`). The SDK's matcher type stays `"literal"` for both.

    Pass `rules` to reuse a pre-fetched list when upserting multiple rules in
    a row (saves an API round-trip per call).
    """
    name = rule_name or f"agent-{address}"
    actions: list[dict[str, Any]] = [{"type": "worker", "value": [worker_name]}]
    matchers: list[dict[str, Any]] = [{"type": "literal", "field": "to", "value": address}]
    client = _client()
    existing = _find_rule_by_name(rules if rules is not None else list_routing_rules(zone_id), name)
    if existing:
        return client.email_routing.rules.update(
            existing.tag,
            zone_id=zone_id,
            name=name,
            enabled=True,
            actions=actions,
            matchers=matchers,
            priority=priority,
        )
    return client.email_routing.rules.create(
        zone_id=zone_id,
        name=name,
        enabled=True,
        actions=actions,
        matchers=matchers,
        priority=priority,
    )


def upsert_subaddress_rule(
    zone_id: str,
    local: str,
    domain: str,
    worker_name: str,
    *,
    rules: list[EmailRoutingRule] | None = None,
):
    """Wildcard rule for `local+*@domain` -> worker.

    Uses Cloudflare's wildcard literal matcher (announced 2024). The matcher
    type is `"literal"` with a `+*` glob in the value — no regex required.
    """
    address = f"{local}+*@{domain}"
    return upsert_worker_route_rule(
        zone_id,
        address,
        worker_name,
        rule_name=f"agent-{local}-subaddress",
        priority=1,
        rules=rules,
    )


def delete_routing_rule(zone_id: str, rule_tag: str):
    return _client().email_routing.rules.delete(rule_tag, zone_id=zone_id)


def send_email(
    account_id: str,
    *,
    from_addr: str,
    to_addr: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    in_reply_to: str | None = None,
) -> dict:
    """Send via the Email Sending REST API.

    Endpoint: POST /accounts/{account_id}/email/sending/send.
    Not yet exposed by `cloudflare` v4.3.1 — direct REST call. Field names
    follow the REST shape (`from.address`), not the Workers binding
    (`from.email`).

    `in_reply_to`, when set, is the Message-Id of a parent email. We map it
    to the `In-Reply-To` and `References` headers per RFC 5322 — distinct
    from CF's `reply_to` REST field, which sets the Reply-To envelope
    address.
    """
    payload: dict[str, Any] = {
        "from": {"address": from_addr},
        "to": to_addr,
        "subject": subject,
        "text": body_text,
    }
    if body_html:
        payload["html"] = body_html
    if in_reply_to:
        payload["headers"] = {"In-Reply-To": in_reply_to, "References": in_reply_to}
    with httpx.Client(
        base_url=SEND_BASE_URL,
        headers={"Authorization": f"Bearer {cf_api_token()}"},
        timeout=30.0,
    ) as c:
        r = c.post(f"/accounts/{account_id}/email/sending/send", json=payload)
        if r.status_code >= 400:
            # Surface CF's error detail (e.g. "Sender domain not verified")
            # instead of letting raise_for_status() swallow the response body.
            try:
                body = r.json()
            except ValueError:
                body = {"raw": r.text}
            raise RuntimeError(
                f"Email Sending API returned {r.status_code}: {json.dumps(body)}"
            )
        return r.json()
