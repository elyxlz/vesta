"""The voice service: the engine socket and the HTTP routes, on one port.

`voice daemon start` runs it as `voice serve`. It reads SKILL_PORT from the environment.
"""

import datetime as dt
import json
import os
import signal
import time
import typing as tp
from pathlib import Path

import aiohttp
from aiohttp import web

from . import appkeys, handlers
from . import config as voice_config
from .engine import session


async def _provider_http(app: web.Application) -> tp.AsyncIterator[None]:
    async with aiohttp.ClientSession() as http:
        app[appkeys.HTTP] = http
        yield


async def _health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


def create_app(data_dir: Path | None = None) -> web.Application:
    app = web.Application()
    app[appkeys.DATA_DIR] = data_dir if data_dir is not None else voice_config.data_dir()
    app[appkeys.PLAYS] = {}
    app.cleanup_ctx.append(_provider_http)

    # The engine: one socket for each session, and the audio of each play
    app.router.add_get("/voice/session", session.voice_session)
    app.router.add_get("/voice/play/{token}", session.voice_play)

    # STT
    app.router.add_get("/stt/status", handlers.stt_status)
    app.router.add_get("/stt/usage", handlers.stt_usage)
    app.router.add_post("/stt/set-enabled", handlers.stt_set_enabled)
    app.router.add_post("/stt/set-eot", handlers.stt_set_eot)
    app.router.add_post("/stt/use", handlers.stt_use)
    app.router.add_get("/stt/listen", handlers.stt_listen)

    # TTS
    app.router.add_get("/tts/status", handlers.tts_status)
    app.router.add_get("/tts/usage", handlers.tts_usage)
    app.router.add_post("/tts/set-enabled", handlers.tts_set_enabled)
    app.router.add_post("/tts/set-voice", handlers.tts_set_voice)
    app.router.add_post("/tts/use", handlers.tts_use)
    app.router.add_post("/tts/speak", handlers.tts_speak)
    app.router.add_post("/tts/prepare", handlers.tts_prepare)
    app.router.add_get("/tts/stream/{id}", handlers.tts_stream)

    # Behaviors, and the generic setter (one provider setting or one behavior)
    app.router.add_get("/behavior/status", handlers.behavior_status)
    app.router.add_post("/{domain:stt|tts|behavior}/set", handlers.set_setting)

    # Health
    app.router.add_get("/health", _health)

    return app


def write_daemon_died(notifications_dir: Path) -> None:
    """Record the server's exit so the agent restarts it, which is news for every exit but
    the SIGTERM `voice daemon stop` sends."""
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
        # SIGTERM is what `voice daemon stop` sends, so it is the one exit the agent asked
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
