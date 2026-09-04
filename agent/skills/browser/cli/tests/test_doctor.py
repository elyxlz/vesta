import asyncio
import sys

import pytest
from vesta_browser import serve
from vesta_browser.runtime_paths import load_paths

from .fakes import write_fakes


def test_doctor_reports_daemon_engines_sessions_and_disk(tmp_path):
    env = write_fakes(tmp_path / "bin")
    env["VESTA_BROWSER_CAMOUFOX_PYTHON"] = sys.executable
    paths = load_paths(env, tmp_path)

    async def run():
        server = asyncio.create_task(serve.serve(paths))
        for _ in range(100):
            if paths.socket.exists():
                break
            await asyncio.sleep(0.02)
        try:
            return await serve.request(paths, {"version": 1, "op": "doctor", "request_id": "d"})
        finally:
            server.cancel()
            with pytest.raises(asyncio.CancelledError):
                await server

    res = asyncio.run(run())
    data = res["data"]
    assert data["daemon"]["protocol_version"] == 1 and data["daemon"]["socket"] == str(paths.socket)
    assert data["engines"]["routes"]["standard"]["ready"] is True
    assert data["engines"]["routes"]["stealth"]["ready"] is False
    assert data["engines"]["versions"]["camoufox"] == "unavailable"  # the test interpreter has no camoufox
    assert data["sessions"] == [] and data["artifacts"]["bytes"] == 0 and data["last_error"] is None
