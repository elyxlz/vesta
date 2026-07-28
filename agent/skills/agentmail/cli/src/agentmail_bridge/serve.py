"""agentmail serve: local HTTP service that AgentMail's webhook POSTs to.

Writes each inbound message to ~/agent/notifications/ as a JSON file the agent
notification loop will pick up. Same shape pattern as cloudflare-email.

Auth: AgentMail's webhook URL includes a `?secret=...` query param matching
$AGENTMAIL_WEBHOOK_SECRET. The handler rejects mismatches with 401.
"""

from __future__ import annotations

import json
import secrets as secrets_mod
import signal
import time
from datetime import UTC, datetime

import click
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request

from agentmail_bridge.config import NOTIFICATIONS_DIR, webhook_secret

app = FastAPI(title="agentmail")


def _field(payload: dict, key: str, default):
    if key in payload and payload[key] is not None:
        return payload[key]
    return default


@app.get("/health")
def health() -> dict:
    """Liveness only, so it answers before the inbox is configured. `agentmail status` has the address."""
    return {"ok": True}


@app.post("/webhook")
async def webhook(request: Request, secret: str = Query(default="")) -> dict:
    """AgentMail POSTs each inbound email here. Authenticated via ?secret= query."""
    # Re-read on every request so `agentmail setup` rotation takes effect without restart.
    expected = webhook_secret()
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

    # Match email-client's header-only notification shape: drop body_text/body_html
    # so inbound mail doesn't dump the full body into the agent's context. The
    # agent fetches the body on demand via `agentmail thread get <thread_id>`.
    notification = {
        "source": "agentmail",
        "type": "message",
        # Inbound mail pools by default so it doesn't preempt the agent mid-task; the user adds interrupt
        # rules (e.g. --keyword urgent) for the mail that should reach them right away.
        "interrupt": False,
        "message_id": _field(message, "message_id", _field(payload, "message_id", "")),
        "thread_id": _field(payload, "thread_id", _field(message, "thread_id", "")),
        "from": _field(message, "from", ""),
        "to": _field(message, "to", ""),
        "subject": _field(message, "subject", ""),
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
    tmp.replace(final)
    return {"ok": True, "notification_path": str(final)}


def _write_daemon_died() -> None:
    """Record the mail service's exit so the agent restarts it: uvicorn returns on a signal and
    raises on a bind/fatal error, so a dead inbound-mail listener is reported either way.
    interrupt defaults on (silent mail loss is urgent)."""
    NOTIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    notif = {
        "source": "agentmail",
        "type": "daemon_died",
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    fname = f"{int(time.time() * 1e6)}-agentmail-daemon_died.json"
    tmp = NOTIFICATIONS_DIR / f"{fname}.tmp"
    tmp.write_text(json.dumps(notif, indent=2))
    tmp.replace(NOTIFICATIONS_DIR / fname)


@click.command("serve")
@click.option("--port", required=True, type=int, help="Port to bind to")
@click.option("--host", default="0.0.0.0", help="Bind address")
def serve_cmd(port: int, host: str) -> None:
    """Run the local HTTP service that receives inbound mail from AgentMail."""
    asked_to_stop = False

    def handle_signal(signum: int, _frame: object) -> None:
        # SIGTERM is what `agentmail daemon stop` sends, so it is the one exit the agent asked
        # for; every other way out of uvicorn is news the agent needs. uvicorn takes both signals
        # over for its graceful shutdown and re-raises them once it has restored these handlers.
        nonlocal asked_to_stop
        asked_to_stop = signum == signal.SIGTERM
        raise SystemExit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        if not asked_to_stop:
            _write_daemon_died()
