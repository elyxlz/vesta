"""Thin REST wrapper around the AgentMail API.

Endpoints + shapes follow https://docs.agentmail.to/llms-full.txt. AgentMail
publishes a Python SDK; this module is a small first-party shim. Swap to the
SDK once dependency footprint is acceptable.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from agentmail.config import API_BASE_URL, api_key


def _client(token: str | None = None) -> httpx.Client:
    return httpx.Client(
        base_url=API_BASE_URL,
        headers={"Authorization": f"Bearer {token or api_key()}"},
        timeout=30.0,
    )


def _raise_with_body(r: httpx.Response, action: str) -> None:
    if r.status_code < 400:
        return
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text}
    raise RuntimeError(f"AgentMail {action} returned {r.status_code}: {json.dumps(body)}")


def sign_up(human_email: str, username: str) -> dict:
    """Start sign-up. Returns server response (typically empty plus 200)."""
    with httpx.Client(base_url=API_BASE_URL, timeout=30.0) as c:
        r = c.post(
            "/agent/sign-up",
            json={"human_email": human_email, "username": username},
        )
        _raise_with_body(r, "sign-up")
        return r.json() if r.text else {}


def verify_signup(human_email: str, otp: str) -> dict:
    """Verify the OTP from sign-up. Returns api_key, inbox_id, organization_id."""
    with httpx.Client(base_url=API_BASE_URL, timeout=30.0) as c:
        r = c.post(
            "/agent/verify",
            json={"human_email": human_email, "otp": otp},
        )
        _raise_with_body(r, "verify")
        return r.json()


def create_inbox(
    *,
    username: str | None = None,
    domain: str | None = None,
    display_name: str | None = None,
    client_id: str | None = None,
) -> dict:
    """Create an inbox. Returns inbox_id, email_address, etc."""
    payload: dict[str, Any] = {}
    if username is not None:
        payload["username"] = username
    if domain is not None:
        payload["domain"] = domain
    if display_name is not None:
        payload["display_name"] = display_name
    if client_id is not None:
        payload["client_id"] = client_id
    with _client() as c:
        r = c.post("/inboxes", json=payload)
        _raise_with_body(r, "create_inbox")
        return r.json()


def list_inboxes() -> list[dict]:
    with _client() as c:
        r = c.get("/inboxes")
        _raise_with_body(r, "list_inboxes")
        body = r.json()
        if isinstance(body, list):
            return body
        if "inboxes" in body:
            return body["inboxes"]
        return []


def delete_inbox(inbox_id: str) -> None:
    with _client() as c:
        r = c.delete(f"/inboxes/{inbox_id}")
        _raise_with_body(r, "delete_inbox")


def send_message(
    inbox_id: str,
    *,
    to_addr: str,
    subject: str,
    text: str,
    html: str | None = None,
    in_reply_to: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
) -> dict:
    payload: dict[str, Any] = {
        "to": to_addr,
        "subject": subject,
        "text": text,
    }
    if html:
        payload["html"] = html
    if cc:
        payload["cc"] = cc
    if bcc:
        payload["bcc"] = bcc
    if in_reply_to:
        # AgentMail accepts custom headers via `headers` per the docs index.
        payload["headers"] = {"In-Reply-To": in_reply_to, "References": in_reply_to}
    with _client() as c:
        r = c.post(f"/inboxes/{inbox_id}/messages/send", json=payload)
        _raise_with_body(r, "send_message")
        return r.json()


def register_webhook(*, url: str, event_types: list[str] | None = None) -> dict:
    """Register a webhook for inbound mail.

    AgentMail's webhook config endpoint is documented as POST to an
    org-scoped webhook resource. The exact path may evolve; verify against
    https://docs.agentmail.to/api-reference/webhooks once you have an
    account, and adjust if the response 404s.
    """
    payload: dict[str, Any] = {"url": url}
    if event_types is not None:
        payload["event_types"] = event_types
    with _client() as c:
        r = c.post("/webhooks", json=payload)
        _raise_with_body(r, "register_webhook")
        return r.json()


def list_webhooks() -> list[dict]:
    with _client() as c:
        r = c.get("/webhooks")
        _raise_with_body(r, "list_webhooks")
        body = r.json()
        if isinstance(body, list):
            return body
        if "webhooks" in body:
            return body["webhooks"]
        return []


def delete_webhook(webhook_id: str) -> None:
    with _client() as c:
        r = c.delete(f"/webhooks/{webhook_id}")
        _raise_with_body(r, "delete_webhook")
