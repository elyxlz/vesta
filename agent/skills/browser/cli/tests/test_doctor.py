import asyncio
import os
import stat
import sys
import time

import pytest
from vesta_browser import doctor, serve
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


def test_doctor_kills_a_hung_version_probe(tmp_path, monkeypatch):
    env = write_fakes(tmp_path / "bin")
    env["VESTA_BROWSER_CAMOUFOX_PYTHON"] = sys.executable
    pid_file = tmp_path / "chromium.pid"
    hang_script = tmp_path / "bin" / "hang-chromium"
    hang_script.write_text(
        f"#!{sys.executable}\nimport os, pathlib, time\npathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\ntime.sleep(30)\n"
    )
    hang_script.chmod(hang_script.stat().st_mode | stat.S_IEXEC)
    env["VESTA_BROWSER_CHROMIUM"] = str(hang_script)
    monkeypatch.setattr(doctor, "VERSION_PROBE_TIMEOUT_SECS", 0.5)
    paths = load_paths(env, tmp_path)

    data = asyncio.run(doctor.versions(paths))
    assert data["chromium"] == "unavailable"

    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        pytest.fail("hung chromium probe process was not killed")
