"""Standalone voice skill HTTP server.

Started by the agent via the `voice-server` command.
Reads SKILL_PORT from environment.
"""

import datetime as dt
import json
import os
import signal
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
    """Record the voice-server's exit so the agent restarts it, which is news for every exit but
    the SIGTERM `voice-keys daemon stop` sends."""
    notifications_dir.mkdir(parents=True, exist_ok=True)
    notif = {"source": "voice", "type": "daemon_died", "timestamp": dt.datetime.now(dt.UTC).isoformat()}
    fname = f"{int(time.time() * 1e6)}-voice-daemon_died.json"
    tmp = notifications_dir / f"{fname}.tmp"
    tmp.write_text(json.dumps(notif, indent=2))
    tmp.replace(notifications_dir / fname)


def main() -> None:
    port = int(os.environ["SKILL_PORT"])
    asked_to_stop = False

    def handle_signal(signum: int, _frame: object) -> None:
        # SIGTERM is what `voice-keys daemon stop` sends, so it is the one exit the agent asked
        # for; every other way out of the server is news the agent needs.
        nonlocal asked_to_stop
        asked_to_stop = signum == signal.SIGTERM
        raise SystemExit(0)

    # Installed before the server comes up, and handle_signals=False keeps them installed:
    # aiohttp's own handlers treat every signal alike, which is the distinction this needs.
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    try:
        web.run_app(create_app(), host="0.0.0.0", port=port, print=lambda *_: None, handle_signals=False)
    finally:
        if not asked_to_stop:
            write_daemon_died(Path.home() / "agent" / "notifications")


if __name__ == "__main__":
    main()
