"""Standalone voice skill HTTP server.

Started by the agent via the `voice-server` command.
Reads SKILL_PORT from environment.
"""

import datetime as dt
import json
import os
import time
from pathlib import Path

from aiohttp import web

from . import handlers


def create_app() -> web.Application:
    app = web.Application()

    # STT
    app.router.add_get("/stt/status", handlers.stt_status)
    app.router.add_get("/stt/usage", handlers.stt_usage)
    app.router.add_post("/stt/set-enabled", handlers.stt_set_enabled)
    app.router.add_post("/stt/set-auto-send", handlers.stt_set_auto_send)
    app.router.add_post("/stt/set-eot", handlers.stt_set_eot)
    app.router.add_get("/stt/listen", handlers.stt_listen)

    # TTS
    app.router.add_get("/tts/status", handlers.tts_status)
    app.router.add_get("/tts/usage", handlers.tts_usage)
    app.router.add_post("/tts/set-enabled", handlers.tts_set_enabled)
    app.router.add_post("/tts/set-voice", handlers.tts_set_voice)
    app.router.add_post("/tts/speak", handlers.tts_speak)
    app.router.add_post("/tts/prepare", handlers.tts_prepare)
    app.router.add_get("/tts/stream/{id}", handlers.tts_stream)

    # Generic setter (works for any provider setting)
    app.router.add_post("/{domain:stt|tts}/set", handlers.set_setting)

    # Health
    app.router.add_get("/health", lambda _: web.Response(text="ok"))

    return app


def write_daemon_died(notifications_dir: Path) -> None:
    """Record the voice-server's exit so the agent restarts it. `voice-keys daemon stop/restart`
    quits the screen session (SIGHUP), which terminates before this runs, so a deliberate
    restart raises no false alarm; a crash or a container stop does write it."""
    notifications_dir.mkdir(parents=True, exist_ok=True)
    notif = {"source": "voice", "type": "daemon_died", "timestamp": dt.datetime.now(dt.UTC).isoformat()}
    fname = f"{int(time.time() * 1e6)}-voice-daemon_died.json"
    tmp = notifications_dir / f"{fname}.tmp"
    tmp.write_text(json.dumps(notif, indent=2))
    tmp.replace(notifications_dir / fname)


def main() -> None:
    port = int(os.environ["SKILL_PORT"])
    try:
        web.run_app(create_app(), host="0.0.0.0", port=port, print=lambda *_: None)
    finally:
        write_daemon_died(Path.home() / "agent" / "notifications")


if __name__ == "__main__":
    main()
