"""cloudflare-email serve: local HTTP service that the Worker POSTs inbound mail to.

Writes each inbound message to ~/agent/notifications/ as a JSON file the agent
notification loop will pick up. Same shape pattern as whatsapp/telegram skills.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import UTC, datetime

import click
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request

from cloudflare_email.config import (
    NOTIFICATIONS_DIR,
    email_address,
    worker_secret,
)


app = FastAPI(title="cloudflare-email")


def _field(payload: dict, key: str, default: str | dict) -> str | dict:
    if key in payload and payload[key] is not None:
        return payload[key]
    return default


# Resolved on first /inbound call so a misconfigured serve fails fast with 503.
# The worker secret never rotates without a `cloudflare-email setup` re-run, so
# caching for the lifetime of this process is safe.
_cached_secret: str | None = None


def _resolve_secret() -> str:
    global _cached_secret
    if _cached_secret is None:
        _cached_secret = worker_secret()
    return _cached_secret


@app.get("/health")
def health() -> dict:
    return {"ok": True, "address": email_address()}


@app.post("/inbound")
async def inbound(
    request: Request,
    x_worker_secret: str = Header(default=""),
) -> dict:
    """Worker POSTs each inbound email here."""
    expected = _resolve_secret()
    if not expected:
        raise HTTPException(503, "worker secret not configured. Run `cloudflare-email setup`")
    if not secrets.compare_digest(x_worker_secret, expected):
        raise HTTPException(401, "bad worker secret")

    payload = await request.json()
    message_id = _field(payload, "message_id", "") or f"<{int(time.time() * 1e6)}@local>"
    notification = {
        "source": "cloudflare-email",
        "type": "message",
        "message_id": message_id,
        "from": _field(payload, "from", ""),
        "to": _field(payload, "to", ""),
        "subject": _field(payload, "subject", ""),
        "body_text": _field(payload, "body_text", ""),
        "body_html": _field(payload, "body_html", ""),
        "in_reply_to": _field(payload, "in_reply_to", ""),
        "references": _field(payload, "references", ""),
        "headers": _field(payload, "headers", {}),
        "received_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }

    NOTIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{int(time.time() * 1e6)}-cloudflare-email-message.json"
    final = NOTIFICATIONS_DIR / fname
    # Atomic write: agent's notification monitor must never read a partial file.
    tmp = NOTIFICATIONS_DIR / f"{fname}.tmp"
    tmp.write_text(json.dumps(notification, indent=2))
    os.replace(tmp, final)
    return {"ok": True, "notification_path": str(final)}


@click.command("serve")
@click.option("--port", required=True, type=int, help="Port to bind to")
@click.option("--host", default="0.0.0.0", help="Bind address")
def serve_cmd(port: int, host: str) -> None:
    """Run the local HTTP service that receives inbound mail from the Worker."""
    uvicorn.run(app, host=host, port=port, log_level="info")
