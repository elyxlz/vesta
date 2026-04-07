"""Standalone voice skill HTTP server.

Started by the agent via `uv run python -m voice.server`.
Reads SKILL_PORT from environment.
"""

import os

from aiohttp import web

from . import handlers

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

# Generic setter (works for any provider setting)
app.router.add_post("/{domain:stt|tts}/set", handlers.set_setting)

# Health
app.router.add_get("/health", lambda _: web.Response(text="ok"))


def main() -> None:
    port = int(os.environ["SKILL_PORT"])
    web.run_app(app, host="0.0.0.0", port=port, print=lambda *_: None)


if __name__ == "__main__":
    main()
