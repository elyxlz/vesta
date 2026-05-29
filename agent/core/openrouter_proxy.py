"""Localhost proxy that pins OpenRouter zero-data-retention providers.

Claude Code sends fixed Anthropic-shaped request bodies and offers no hook to add
OpenRouter's `provider` routing field, which is the only way to enforce ZDR per request.
So when an agent runs via OpenRouter we point ANTHROPIC_BASE_URL at this in-process proxy:
it rewrites each JSON body to require zero-data-retention providers (when enabled) and
streams the upstream response straight back, leaving auth headers untouched.
"""

import json
import socket

import aiohttp
from aiohttp import web

from . import logger

OPENROUTER_UPSTREAM = "https://openrouter.ai/api"
# Stripped from the forwarded request: Host is set by the client lib from the URL,
# Content-Length is recomputed after body rewrite, and we let aiohttp negotiate encoding.
_STRIP_REQUEST_HEADERS = {"host", "content-length", "accept-encoding"}
# Stripped from the response: aiohttp decompresses the body, so the original framing/encoding
# headers no longer describe the bytes we forward.
_STRIP_RESPONSE_HEADERS = {"content-length", "content-encoding", "transfer-encoding", "connection"}


def _zdr_provider() -> dict[str, object]:
    return {"zdr": True, "data_collection": "deny"}


def inject_provider(body: bytes, *, zdr: bool) -> bytes:
    """Merge ZDR provider routing into a JSON request body. Non-JSON bodies pass through."""
    if not zdr or not body:
        return body
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body
    if not isinstance(payload, dict):
        return body
    if "provider" in payload and isinstance(payload["provider"], dict):
        payload["provider"].update(_zdr_provider())
    else:
        payload["provider"] = _zdr_provider()
    return json.dumps(payload).encode()


def _make_handler(session: aiohttp.ClientSession, *, zdr: bool):
    async def handler(request: web.Request) -> web.StreamResponse:
        body = inject_provider(await request.read(), zdr=zdr)
        headers = {k: v for k, v in request.headers.items() if k.lower() not in _STRIP_REQUEST_HEADERS}
        url = OPENROUTER_UPSTREAM + request.raw_path
        try:
            upstream = await session.request(request.method, url, data=body, headers=headers)
        except aiohttp.ClientError as e:
            logger.error(f"openrouter proxy upstream error: {e}")
            return web.Response(status=502, text=f"openrouter proxy error: {e}")

        resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _STRIP_RESPONSE_HEADERS}
        response = web.StreamResponse(status=upstream.status, headers=resp_headers)
        await response.prepare(request)
        try:
            async for chunk in upstream.content.iter_any():
                await response.write(chunk)
        except (aiohttp.ClientError, ConnectionResetError):
            pass
        finally:
            upstream.release()
        await response.write_eof()
        return response

    return handler


async def start_proxy(*, zdr: bool) -> tuple[web.AppRunner, int]:
    """Bind the proxy to an ephemeral localhost port and return (runner, port)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None))
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", _make_handler(session, zdr=zdr))
    app.on_cleanup.append(lambda _app: session.close())

    runner = web.AppRunner(app)
    await runner.setup()
    await web.SockSite(runner, sock).start()
    return runner, port
