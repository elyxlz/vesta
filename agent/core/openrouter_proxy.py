"""Localhost proxy that pins OpenRouter zero-data-retention providers.

Claude Code sends fixed Anthropic-shaped bodies with no hook for OpenRouter's `provider` routing
field, the only per-request way to enforce ZDR. So in OpenRouter mode we point ANTHROPIC_BASE_URL
at this proxy, which injects the field and streams the response back, leaving auth headers untouched.
"""

import json
import socket

import aiohttp
from aiohttp import web

from . import logger
from .api import start_runner

OPENROUTER_UPSTREAM = "https://openrouter.ai/api"
# aiohttp recomputes these from the (rewritten) body and decompresses, so the originals no longer apply.
_STRIP_REQUEST_HEADERS = {"host", "content-length", "accept-encoding"}
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

    runner = await start_runner(app)
    await web.SockSite(runner, sock).start()
    return runner, port
