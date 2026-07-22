import asyncio
import typing as tp

import pytest
from aiohttp import web

from core.codex_proxy import _available_port, _wait_ready


@pytest.mark.anyio
async def test_wait_ready_uses_bridge_healthz_endpoint():
    port = _available_port()
    app = web.Application()
    app.router.add_get("/healthz", lambda _request: web.json_response({"ok": True}))
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
