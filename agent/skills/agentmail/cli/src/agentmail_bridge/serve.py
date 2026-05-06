"""agentmail serve: local HTTP service that AgentMail's webhook POSTs to.

Writes each inbound message to ~/agent/notifications/ as a JSON file the agent
notification loop will pick up. Same shape pattern as cloudflare-email.

Auth: AgentMail's webhook URL includes a `?secret=...` query param matching
$AGENTMAIL_WEBHOOK_SECRET. The handler rejects mismatches with 401.
"""

from __future__ import annotations

import json
import os
import secrets as secrets_mod
import time
from datetime import UTC, datetime

import click
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request

from agentmail_bridge.config import (
    NOTIFICATIONS_DIR,
    email_address,
    webhook_secret,
)


app = FastAPI(title="agentmail")

_cached_secret: str | None = None


def _resolve_secret() -> str:
    global _cached_secret
    if _cached_secret is None:
        _cached_secret = webhook_secret()
    return _cached_secret


def _field(payload: dict, key: str, default):
    if key in payload and payload[key] is not None:
        return payload[key]
    return default


@app.get("/health")
def health() -> dict:
    return {"ok": True, "address": email_address()}


@app.post("/webhook")
async def webhook(request: Request, secret: str = Query(default="")) -> dict:
    """AgentMail POSTs each inbound email here. Authenticated via ?secret= query."""
    expected = _resolve_secret()
    if not expected:
        raise HTTPException(503, "webhook secret not configured. Run `agentmail setup`")
    if not secrets_mod.compare_digest(secret, expected):
        raise HTTPException(401, "bad webhook secret")

    payload = await request.json()
    # AgentMail webhook shape: {event_type, inbox_id, thread_id, message_id, message: {...}}
    message = _field(payload, "message", {})
    if not isinstance(message, dict):
        message = {}

    headers = _field(message, "headers", {})
    if not isinstance(headers, dict):
        headers = {}

    notification = {
        "source": "agentmail",
        "type": "message",
        "message_id": _field(message, "message_id", _field(payload, "message_id", "")),
        "thread_id": _field(payload, "thread_id", _field(message, "thread_id", "")),
        "from": _field(message, "from", ""),
        "to": _field(message, "to", ""),
        "subject": _field(message, "subject", ""),
        "body_text": _field(message, "text", ""),
        "body_html": _field(message, "html", ""),
        "in_reply_to": _field(headers, "In-Reply-To", _field(message, "in_reply_to", "")),
        "references": _field(headers, "References", _field(message, "references", "")),
        "labels": _field(message, "labels", []),
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }

    NOTIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{int(time.time() * 1e6)}-agentmail-message.json"
    final = NOTIFICATIONS_DIR / fname
    tmp = NOTIFICATIONS_DIR / f"{fname}.tmp"
    tmp.write_text(json.dumps(notification, indent=2))
    os.replace(tmp, final)
    return {"ok": True, "notification_path": str(final)}


@click.command("serve")
@click.option("--port", required=True, type=int, help="Port to bind to")
@click.option("--host", default="0.0.0.0", help="Bind address")
def serve_cmd(port: int, host: str) -> None:
    """Run the local HTTP service that receives inbound mail from AgentMail."""
    uvicorn.run(app, host=host, port=port, log_level="info")
