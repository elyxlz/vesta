import asyncio
import typing as tp

import pytest
from aiohttp import web

from core.codex_proxy import _available_port, _wait_ready


@pytest.mark.anyio
async def test_wait_ready_uses_bridge_healthz_endpoint():
    port = _available_port()
    app = web.Application()

    async def healthz(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app.router.add_get("/healthz", healthz)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()

    class _RunningProcess:
        returncode = None

    try:
        process = tp.cast("asyncio.subprocess.Process", _RunningProcess())
        assert await _wait_ready(f"http://127.0.0.1:{port}", process)
    finally:
        await runner.cleanup()
