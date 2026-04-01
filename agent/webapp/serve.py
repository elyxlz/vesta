#!/usr/bin/python3
"""HTTPS reverse-proxy server for the okami webapp.

Serves static files AND proxies WebSocket connections to the vesta
backend — all over a single HTTPS port so mobile browsers don't
block mic access (secure context) or websockets (mixed content).

Also supports pushing audio responses to connected browsers via
POST /api/play — used by okami to send TTS voice replies.
"""

import asyncio
import base64
import json
import os
import ssl

import aiohttp
from aiohttp import web

DIR = os.path.dirname(os.path.abspath(__file__))
CERT = os.path.join(DIR, "cert.pem")
KEY = os.path.join(DIR, "key.pem")
PORT = 8080
WS_BACKEND = "ws://127.0.0.1:7865/ws"

# Track connected browser websockets so we can push audio to them
connected_clients: set[web.WebSocketResponse] = set()


async def ws_proxy(request: web.Request) -> web.WebSocketResponse:
    """Proxy wss:// from browser → plain ws:// to vesta backend."""
    client_ws = web.WebSocketResponse()
    await client_ws.prepare(request)
    connected_clients.add(client_ws)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(WS_BACKEND) as backend_ws:

                async def forward_to_client():
                    async for msg in backend_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await client_ws.send_str(msg.data)
                        elif msg.type == aiohttp.WSMsgType.BINARY:
                            await client_ws.send_bytes(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                            break

                async def forward_to_backend():
                    async for msg in client_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await backend_ws.send_str(msg.data)
                        elif msg.type == aiohttp.WSMsgType.BINARY:
                            await backend_ws.send_bytes(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                            break

                await asyncio.gather(
                    forward_to_client(),
                    forward_to_backend(),
                    return_exceptions=True,
                )
    finally:
        connected_clients.discard(client_ws)

    return client_ws


async def play_audio(request: web.Request) -> web.Response:
    """POST /api/play — push audio to all connected browsers.

    Accepts JSON: {"path": "/tmp/response.ogg"}
    Reads the file, base64-encodes it, and sends an audio_response
    event to all connected websocket clients.
    """
    try:
        data = await request.json()
        path = data.get("path", "")
        if not path or not os.path.isfile(path):
            return web.json_response({"error": "file not found"}, status=404)

        with open(path, "rb") as f:
            audio_bytes = f.read()

        audio_b64 = base64.b64encode(audio_bytes).decode()

        # Determine mime type from extension
        ext = os.path.splitext(path)[1].lower()
        mime_map = {".ogg": "audio/ogg", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4"}
        mime = mime_map.get(ext, "audio/ogg")

        event = json.dumps(
            {
                "type": "audio_response",
                "data": audio_b64,
                "mime": mime,
            }
        )

        sent = 0
        for ws in list(connected_clients):
            if not ws.closed:
                try:
                    await ws.send_str(event)
                    sent += 1
                except Exception:
                    connected_clients.discard(ws)

        return web.json_response({"ok": True, "sent_to": sent})

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def index_handler(request: web.Request) -> web.FileResponse:
    """Serve index.html for the root path."""
    return web.FileResponse(os.path.join(DIR, "index.html"))


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/ws", ws_proxy)
    app.router.add_post("/api/play", play_audio)
    app.router.add_get("/", index_handler)
    app.router.add_static("/", DIR, show_index=False)
    return app


def main():
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(CERT, KEY)

    app = make_app()
    print(f"HTTPS server running on https://0.0.0.0:{PORT}")
    web.run_app(app, host="0.0.0.0", port=PORT, ssl_context=ssl_ctx, print=None)


if __name__ == "__main__":
    main()
