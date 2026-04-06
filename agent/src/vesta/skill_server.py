"""Reverse proxy for skill HTTP servers.

Skills that run their own HTTP server register here. The agent adds entries
to SKILL_SERVERS (same pattern as the old SKILL_ENDPOINTS) and restarts.
The catch-all handler proxies /{skill_name}/* to localhost:{port}/*.
"""

import asyncio

import aiohttp
from aiohttp import web

from vesta import logger

# Skill HTTP servers. Append one row per running skill server.
# Format: (SKILL_NAME, PORT). The proxy strips the /{skill_name} prefix
# and forwards to http://localhost:{port}/{rest_of_path}.
# Example: ("voice", 7965) proxies /voice/stt/status -> localhost:7965/stt/status
SKILL_SERVERS: list[tuple[str, int]] = []


async def skill_proxy_handler(request: web.Request) -> web.StreamResponse:
    """Catch-all handler: proxy to skill server based on first path segment."""
    skill_name = request.match_info["skill_name"]
    path_info = request.match_info.get("path_info", "")

    port = _get_port(skill_name)
    if port is None:
        return web.json_response({"error": f"unknown skill: {skill_name}"}, status=404)

    target_path = f"/{path_info}" if path_info else "/"
    if request.query_string:
        target_path = f"{target_path}?{request.query_string}"

    # WebSocket upgrade
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await _ws_proxy(request, port, target_path)

    # HTTP proxy
    return await _http_proxy(request, port, target_path)


async def _http_proxy(request: web.Request, port: int, target_path: str) -> web.StreamResponse:
    """Forward HTTP request to skill server, stream response back."""
    url = f"http://localhost:{port}{target_path}"

    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "connection", "transfer-encoding", "content-length")}

    body = await request.read()

    session: aiohttp.ClientSession = request.app["_skill_proxy_session"]
    try:
        async with session.request(
            request.method,
            url,
            headers=headers,
            data=body if body else None,
        ) as upstream:
            response = web.StreamResponse(status=upstream.status)
            for k, v in upstream.headers.items():
                if k.lower() not in ("transfer-encoding", "connection", "content-length"):
                    response.headers[k] = v
            await response.prepare(request)

            async for chunk in upstream.content.iter_any():
                await response.write(chunk)

            await response.write_eof()
            return response
    except aiohttp.ClientError as exc:
        logger.error(f"[{request.match_info['skill_name']}] proxy error: {exc}")
        return web.json_response({"error": "skill server unreachable"}, status=502)


async def _ws_proxy(request: web.Request, port: int, target_path: str) -> web.WebSocketResponse:
    """Bidirectional WebSocket relay to skill server."""
    url = f"ws://localhost:{port}{target_path}"

    client_ws = web.WebSocketResponse()
    await client_ws.prepare(request)

    session: aiohttp.ClientSession = request.app["_skill_proxy_session"]
    try:
        async with session.ws_connect(url) as skill_ws:

            async def client_to_skill() -> None:
                async for msg in client_ws:
                    if msg.type == web.WSMsgType.TEXT:
                        await skill_ws.send_str(msg.data)
                    elif msg.type == web.WSMsgType.BINARY:
                        await skill_ws.send_bytes(msg.data)
                    elif msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.ERROR):
                        break

            async def skill_to_client() -> None:
                async for msg in skill_ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await client_ws.send_str(msg.data)
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        await client_ws.send_bytes(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                        break

            tasks = [
                asyncio.create_task(client_to_skill()),
                asyncio.create_task(skill_to_client()),
            ]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                task.cancel()

    except (aiohttp.ClientError, aiohttp.WSServerHandshakeError) as exc:
        logger.error(f"[{request.match_info['skill_name']}] ws proxy error: {exc}")
        if not client_ws.closed:
            await client_ws.close(code=1011, message=b"skill server unreachable")

    return client_ws


def _get_port(name: str) -> int | None:
    for skill_name, port in SKILL_SERVERS:
        if skill_name == name:
            return port
    return None


def wire_skill_proxies(app: web.Application) -> None:
    """Register the catch-all proxy route for all entries in SKILL_SERVERS.
    Called once at startup. Also sets up a shared ClientSession."""
    if not SKILL_SERVERS:
        return

    for name, port in SKILL_SERVERS:
        logger.startup(f"wired skill proxy /{name}/* -> localhost:{port}")

    app.router.add_route("*", "/{skill_name}/{path_info:.*}", skill_proxy_handler)

    async def create_session(app: web.Application) -> None:
        app["_skill_proxy_session"] = aiohttp.ClientSession()

    async def close_session(app: web.Application) -> None:
        session = app.get("_skill_proxy_session")
        if session:
            await session.close()

    app.on_startup.append(create_session)
    app.on_cleanup.append(close_session)
