"""cloudflare-email serve: local HTTP service that the Worker POSTs inbound mail to.

Writes each inbound message to ~/agent/notifications/ as a JSON file the agent
notification loop will pick up. Same shape pattern as whatsapp/telegram skills.
"""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request

from cloudflare_email.config import (
    NOTIFICATIONS_DIR,
    email_address,
    worker_secret,
)


app = FastAPI(title="cloudflare-email")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "address": email_address()}


@app.post("/inbound")
async def inbound(
    request: Request,
    x_worker_secret: str = Header(default=""),
) -> dict:
    """Worker POSTs each inbound email here."""
    expected = worker_secret()
    if not expected:
        raise HTTPException(503, "worker secret not configured. Run `cloudflare-email setup`")
    # constant-time compare
    if not secrets.compare_digest(x_worker_secret, expected):
        raise HTTPException(401, "bad worker secret")

    payload = await request.json()
    message_id = payload.get("message_id") or str(uuid.uuid4())
    notification = {
        "source": "cloudflare-email",
        "type": "message",
        "message_id": message_id,
        "from": payload.get("from", ""),
        "to": payload.get("to", ""),
        "subject": payload.get("subject", ""),
        "body_text": payload.get("body_text", ""),
        "body_html": payload.get("body_html", ""),
        "headers": payload.get("headers", {}),
        "received_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    NOTIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4()}-cloudflare-email-message.json"
    path = NOTIFICATIONS_DIR / fname
    path.write_text(json.dumps(notification, indent=2))
    return {"ok": True, "notification_path": str(path)}


@click.command("serve")
@click.option("--port", required=True, type=int, help="Port to bind to")
@click.option("--host", default="0.0.0.0", help="Bind address")
def serve_cmd(port: int, host: str) -> None:
    """Run the local HTTP service that receives inbound mail from the Worker."""
    uvicorn.run(app, host=host, port=port, log_level="info")
