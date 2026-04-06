"""Reverse proxy — routes /{name}/* to localhost:{port}/*.

Any process inside the container can be made reachable from the outside by
registering a (name, port) tuple in PROXIED_SERVERS. The agent's single
exposed port then proxies HTTP and WebSocket traffic to that process,
like a minimal nginx.
"""

import asyncio

import aiohttp
from aiohttp import web

from vesta import logger

# (name, port) — the proxy strips the /{name} prefix.
# Example: ("voice", 7965) proxies /voice/stt/status -> localhost:7965/stt/status
PROXIED_SERVERS: list[tuple[str, int]] = []

_session: aiohttp.ClientSession | None = None


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


def _get_port(name: str) -> int | None:
    for skill_name, port in PROXIED_SERVERS:
        if skill_name == name:
            return port
    return None


async def skill_proxy_handler(request: web.Request) -> web.StreamResponse:
    """Catch-all handler: proxy to skill server based on first path segment."""
    skill_name = request.match_info["skill_name"]
    rest = request.match_info.get("path_info", "")
    port = _get_port(skill_name)
    if port is None:
        return web.json_response({"error": f"unknown skill: {skill_name}"}, status=404)

    target = f"/{rest}" if rest else "/"
    if request.query_string:
        target = f"{target}?{request.query_string}"

    session = await _get_session()

    # WebSocket
    if request.headers.get("Upgrade", "").lower() == "websocket":
        client_ws = web.WebSocketResponse()
        await client_ws.prepare(request)
        try:
            async with session.ws_connect(f"ws://localhost:{port}{target}") as skill_ws:

                async def fwd(src, dst):  # type: ignore[no-untyped-def]
                    async for msg in src:
                        if msg.type in (aiohttp.WSMsgType.TEXT, web.WSMsgType.TEXT):
                            await dst.send_str(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.BINARY, web.WSMsgType.BINARY):
                            await dst.send_bytes(msg.data)
                        else:
                            break

                tasks = [
                    asyncio.create_task(fwd(client_ws, skill_ws)),
                    asyncio.create_task(fwd(skill_ws, client_ws)),
                ]
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in tasks:
                    task.cancel()
        except (aiohttp.ClientError, aiohttp.WSServerHandshakeError) as exc:
            logger.error(f"[{skill_name}] ws proxy error: {exc}")
            if not client_ws.closed:
                await client_ws.close(code=1011, message=b"skill server unreachable")
        return client_ws

    # HTTP
    try:
        headers = {
            k: v for k, v in request.headers.items() if k.lower() not in ("host", "connection", "transfer-encoding", "content-length")
        }
        body = await request.read()
        async with session.request(request.method, f"http://localhost:{port}{target}", headers=headers, data=body or None) as resp:
            return web.Response(
                body=await resp.read(),
                status=resp.status,
                headers={k: v for k, v in resp.headers.items() if k.lower() not in ("transfer-encoding", "connection", "content-length")},
            )
    except aiohttp.ClientError as exc:
        logger.error(f"[{skill_name}] proxy error: {exc}")
        return web.json_response({"error": "skill server unreachable"}, status=502)


def wire_proxies(app: web.Application) -> None:
    """Register the catch-all proxy route. Called once at startup."""
    if not PROXIED_SERVERS:
        return
    for name, port in PROXIED_SERVERS:
        logger.startup(f"wired skill proxy /{name}/* -> localhost:{port}")
    app.router.add_route("*", "/{skill_name}/{path_info:.*}", skill_proxy_handler)
