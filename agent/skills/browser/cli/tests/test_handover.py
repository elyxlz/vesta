"""The handover: the session's own display streamed to one keyed URL, and one clean teardown."""

import asyncio
import contextlib
import datetime as dt
import json
import os
import pathlib as pl
import shutil
import signal
import sys
import tempfile
import time
import urllib.request

import pytest
from vesta_browser import display, handover, serve
from vesta_browser.runtime_paths import load_paths

from .fakes import write_display_fakes, write_fakes, write_script
from .hermetic import isolated_path
from .waiting import (
    POLL_DEADLINE_SECS,
    POLL_INTERVAL_SECS,
    pid_alive,
    wait_for_state,
    wait_until_all_dead,
    wait_until_dead,
    with_daemon,
)

FAKE_CAMOUFOX = pl.Path(__file__).parent / "fake_camoufox"
PUBLIC_URL = "https://gw.example"
AGENT = "luna"
WEB_PORT_FIRST = 6180
HTTP_TIMEOUT_SECS = 5
EXPIRY_DEADLINE_SECS = 3.0
# Short enough to fire well inside the fake x11vnc's own readiness wait, so the budget is what answers.
BUDGET_SECS = 2.0


class Rig:
    """Everything a handover test needs: the daemon's paths, the web port, and the fakes' records."""

    def __init__(self, paths, tmp_path, x11_dir, web_port):
        self.paths = paths
        self.tmp_path = tmp_path
        self.x11_dir = x11_dir
        self.web_port = web_port

    def keys(self):
        record = self.tmp_path / "keys.json"
        return json.loads(record.read_text()) if record.exists() else []

    def register_lines(self):
        """Every gateway call the run made, the daemon's own startup deregister first."""
        record = self.tmp_path / "register.log"
        return record.read_text().splitlines() if record.exists() else []

    def display_pids(self):
        record = self.x11_dir / "pids"
        return [int(line) for line in record.read_text().split()] if record.exists() else []


@pytest.fixture
def rig(tmp_path, monkeypatch):
    # AF_UNIX addresses cap at 108 bytes and a pytest tmp_path plus the X socket name can pass it.
    x11_dir = pl.Path(tempfile.mkdtemp(dir="/tmp"))
    bin_dir = isolated_path(tmp_path, monkeypatch)
    env = write_fakes(bin_dir)
    write_display_fakes(bin_dir, x11_dir)
    novnc = tmp_path / "novnc"
    (novnc / "core").mkdir(parents=True)
    (novnc / "core" / "rfb.js").write_text("export default class RFB {}\n")
    (novnc / "vendor").mkdir()
    camoufox_exe = tmp_path / "camoufox"
    camoufox_exe.write_text("")
    env.update(
        {
            "VESTA_BROWSER_CAMOUFOX_PYTHON": sys.executable,
            "VESTA_BROWSER_CAMOUFOX_EXE": str(camoufox_exe),
            "VESTA_BROWSER_NOVNC_DIR": str(novnc),
            "VESTA_BROWSER_X11_DIR": str(x11_dir),
        }
    )
    web_port = display.free_port(WEB_PORT_FIRST)
    monkeypatch.setenv("PYTHONPATH", str(FAKE_CAMOUFOX))
    monkeypatch.setenv("FAKE_KEYS", str(tmp_path / "keys.json"))
    monkeypatch.setenv("FAKE_REGISTER_LOG", str(tmp_path / "register.log"))
    monkeypatch.setenv("FAKE_PORT", str(web_port))
    monkeypatch.setenv("VESTAD_PUBLIC_URL", PUBLIC_URL)
    monkeypatch.setenv("AGENT_NAME", AGENT)
    yield Rig(load_paths(env, tmp_path), tmp_path, x11_dir, web_port)
    shutil.rmtree(x11_dir, ignore_errors=True)


def _start(session="research", mode=None, url=None, minutes=None, request_id="h1"):
    return {
        "version": 1,
        "op": "handover_start",
        "request_id": request_id,
        "session": session,
        "mode": mode,
        "url": url,
        "minutes": minutes,
    }


def _op(op, request_id="h2"):
    return {"version": 1, "op": op, "request_id": request_id}


def _exec(session, code, request_id="e1"):
    return {"version": 1, "op": "exec", "request_id": request_id, "session": session, "mode": None, "timeout_s": 10, "code": code}


def _fetch(url):
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SECS) as answer:
        return answer.status


async def _wait_for_pids(rig, wanted):
    deadline = time.monotonic() + POLL_DEADLINE_SECS
    while time.monotonic() < deadline:
        if len(rig.display_pids()) >= wanted:
            return
        await asyncio.sleep(POLL_INTERVAL_SECS)
    raise AssertionError(f"only {len(rig.display_pids())} display processes started, wanted {wanted}")


def _await_all_dead(pids):
    deadline = time.monotonic() + EXPIRY_DEADLINE_SECS
    while time.monotonic() < deadline and any(pid_alive(pid) for pid in pids):
        time.sleep(POLL_INTERVAL_SECS)
    return not any(pid_alive(pid) for pid in pids)


def _minutes_ahead(stamp):
    when = dt.datetime.fromisoformat(stamp)
    return (when - dt.datetime.now(dt.UTC)).total_seconds() / 60


def test_handover_start_serves_the_page_and_hands_the_session_over(rig):
    async def run():
        started = await serve.request(rig.paths, _start(url="https://example.com/"))
        try:
            await _wait_for_pids(rig, 4)
            status = await serve.request(rig.paths, _op("handover_status"))
            listing = await serve.request(rig.paths, _op("sessions", request_id="h3"))
            page = await asyncio.to_thread(_fetch, f"http://127.0.0.1:{rig.web_port}/handover.html")
            navigate = (rig.paths.sessions / "research/tmp/code.txt").read_text()
            return started, status, listing, page, rig.register_lines(), navigate, rig.display_pids()
        finally:
            await serve.request(rig.paths, _op("handover_stop", request_id="h9"))

    started, status, listing, page, registered, navigate, pids = with_daemon(rig.paths, run)
    assert started["ok"] is True, started
    assert navigate == "switch_tab(new_tab('https://example.com/'), activate=True)"
    data = started["data"]
    assert data["state"] == "live" and data["engine"] == "chromium" and data["session"] == "research"
    assert data["user_url"] == f"{PUBLIC_URL}/agents/{AGENT}/browser/k/secret-browser-handover-{data['handover_id']}/handover.html"
    assert 25 < _minutes_ahead(data["expires_at"]) <= 30
    assert started["session"]["state"] == "handed_over"
    assert status["data"]["state"] == "live"
    assert [s["state"] for s in listing["data"]["sessions"] if s["name"] == "research"] == ["handed_over"]
    assert registered == ["deregister browser", "browser"]
    assert page == 200
    env_seen = json.loads((rig.paths.profiles / "chromium" / "research" / "env.json").read_text())
    assert env_seen["DISPLAY"].startswith(":")
    assert len(pids) == 4


def test_a_handover_streams_a_running_session_and_gives_the_browser_back(rig):
    """The display and the browser are the session's own: a handover adds a stream and drops it."""

    async def run():
        first = await serve.request(rig.paths, _exec("research", "print(1)"))
        await _wait_for_pids(rig, 2)
        display_pids = rig.display_pids()
        started = await serve.request(rig.paths, _start())
        await _wait_for_pids(rig, 4)
        stream_pids = rig.display_pids()[len(display_pids) :]
        stopped = await serve.request(rig.paths, _op("handover_stop"))
        await wait_for_state(rig.paths, "research", "ready")
        gone = await wait_until_all_dead(stream_pids)
        again = await serve.request(rig.paths, _exec("research", "print(2)", request_id="e2"))
        held = all(pid_alive(pid) for pid in display_pids)
        launched = (rig.paths.profiles / "chromium" / "research" / "launches").read_text().splitlines()
        return first, started, stopped, again, display_pids, stream_pids, gone, held, launched

    first, started, stopped, again, display_pids, stream_pids, gone, held, launched = with_daemon(rig.paths, run)
    assert first["ok"] is True and started["ok"] is True, (first, started)
    assert started["session"]["state"] == "handed_over"
    assert len(display_pids) == 2 and len(stream_pids) == 2
    assert stopped["ok"] is True and stopped["warnings"] == []
    assert gone is True and held is True
    assert again["ok"] is True and again["session"]["state"] == "ready" and again["warnings"] == []
    assert len(launched) == 1


def test_a_stealth_handover_launches_camoufox_headed_for_the_requested_lifetime(rig):
    async def run():
        started = await serve.request(rig.paths, _start(session="stealthy", mode="stealth", minutes=5))
        await _wait_for_pids(rig, 4)
        pids = rig.display_pids()
        launch = json.loads((rig.paths.profiles / "camoufox" / "stealthy" / "launch.json").read_text())
        minted = rig.keys()
        await serve.request(rig.paths, _op("handover_stop", request_id="h9"))
        await wait_for_state(rig.paths, "stealthy", "ready")
        gone = await wait_until_all_dead(pids[2:])
        return started, launch, minted, gone, all(pid_alive(pid) for pid in pids[:2])

    started, launch, minted, gone, held = with_daemon(rig.paths, run)
    assert started["ok"] is True, started
    assert started["data"]["engine"] == "camoufox"
    assert launch["headless"] == "False" and launch["window"] == "(1280, 800)"
    assert [minted_key["ttl"] for minted_key in minted] == [300]
    assert gone is True and held is True


def test_a_handed_over_session_refuses_exec_stop_and_a_second_handover(rig):
    async def run():
        await serve.request(rig.paths, _start())
        try:
            ran = await serve.request(rig.paths, _exec("research", "print(1)"))
            stopped = await serve.request(rig.paths, {"version": 1, "op": "session_stop", "request_id": "h4", "session": "research"})
            again = await serve.request(rig.paths, _start(request_id="h5"))
            return ran, stopped, again
        finally:
            await serve.request(rig.paths, _op("handover_stop", request_id="h9"))

    ran, stopped, again = with_daemon(rig.paths, run)
    assert ran["ok"] is False and ran["error"]["code"] == "handover_in_use"
    assert stopped["ok"] is False and stopped["error"]["code"] == "invalid_request"
    assert again["ok"] is False and again["error"]["code"] == "handover_in_use"


def test_doctor_never_reports_the_handover_key(rig):
    async def run():
        started = await serve.request(rig.paths, _start())
        try:
            return started, await serve.request(rig.paths, _op("doctor", request_id="h8"))
        finally:
            await serve.request(rig.paths, _op("handover_stop", request_id="h9"))

    started, reported = with_daemon(rig.paths, run)
    assert started["ok"] is True and "/k/" in started["data"]["user_url"]
    block = reported["data"]["handover"]
    assert block["state"] == "live" and block["handover_id"] == started["data"]["handover_id"]
    assert "user_url" not in block
    assert "/k/" not in json.dumps(reported)


def test_handover_stop_releases_the_key_the_service_and_the_stream(rig):
    async def run():
        await serve.request(rig.paths, _start())
        await _wait_for_pids(rig, 4)
        pids = rig.display_pids()
        stopped = await serve.request(rig.paths, _op("handover_stop"))
        await wait_for_state(rig.paths, "research", "ready")
        gone = await wait_until_all_dead(pids[2:])
        held = all(pid_alive(pid) for pid in pids[:2])
        ran = await serve.request(rig.paths, _exec("research", "print(1)"))
        status = await serve.request(rig.paths, _op("handover_status", request_id="h6"))
        return stopped, pids, gone, held, ran, status

    stopped, pids, gone, held, ran, status = with_daemon(rig.paths, run)
    assert stopped["ok"] is True and stopped["warnings"] == []
    assert len(pids) == 4 and gone is True and held is True
    assert rig.keys() == []
    assert rig.register_lines() == ["deregister browser", "browser", "deregister browser"]
    assert ran["ok"] is True and ran["session"]["state"] == "ready"
    assert status["data"]["state"] == "inactive" and status["data"]["user_url"] is None
    assert not rig.paths.handover_web.exists()


def test_a_handover_whose_browser_died_gives_the_session_back_stopped(rig):
    """A runtime the user lost is reaped with its display, so the next exec starts a fresh one."""

    async def run():
        await serve.request(rig.paths, _start())
        await _wait_for_pids(rig, 4)
        pids = rig.display_pids()
        browser = int((rig.paths.profiles / "chromium" / "research" / "fake.pid").read_text())
        os.kill(browser, signal.SIGKILL)
        reaped = await wait_until_dead(browser)
        stopped = await serve.request(rig.paths, _op("handover_stop"))
        await wait_for_state(rig.paths, "research", "stopped")
        gone = await wait_until_all_dead(pids)
        again = await serve.request(rig.paths, _exec("research", "print(1)"))
        return reaped, stopped, gone, again

    reaped, stopped, gone, again = with_daemon(rig.paths, run)
    assert reaped is True
    assert stopped["ok"] is True and stopped["warnings"] == []
    assert gone is True
    assert again["ok"] is True and again["warnings"] == ["worker_restarted"]


def test_a_start_whose_engine_never_comes_up_fails_inside_the_one_budget(rig, monkeypatch):
    """The engine start is inside the budget the client waits behind, not beside it."""
    profile = rig.paths.profiles / "chromium" / "research"
    profile.mkdir(parents=True)
    (profile / "no-port").write_text("")
    monkeypatch.setattr(handover, "HANDOVER_START_BUDGET_SECS", BUDGET_SECS)

    async def run():
        began = time.monotonic()
        started = await serve.request(rig.paths, _start())
        elapsed = time.monotonic() - began
        listing = await serve.request(rig.paths, _op("sessions", request_id="h7"))
        gone = await wait_until_all_dead(rig.display_pids())
        status = await serve.request(rig.paths, _op("handover_status"))
        return started, elapsed, listing, gone, status

    started, elapsed, listing, gone, status = with_daemon(rig.paths, run)
    assert started["ok"] is False and started["error"]["code"] == "handover_failed"
    assert f"{BUDGET_SECS}s" in started["error"]["message"]
    assert BUDGET_SECS <= elapsed < 10
    assert [s["state"] for s in listing["data"]["sessions"] if s["name"] == "research"] == ["stopped"]
    assert gone is True
    assert status["data"]["state"] == "inactive"
    assert rig.register_lines() == ["deregister browser"]


def test_two_starts_at_once_leave_exactly_one_handover(rig):
    """The handover record is claimed before the engine start, so the second caller is refused."""

    async def run():
        first, second = await asyncio.gather(
            serve.request(rig.paths, _start(session="one", request_id="h1")),
            serve.request(rig.paths, _start(session="two", request_id="h2")),
        )
        pids = rig.display_pids()
        await serve.request(rig.paths, _op("handover_stop", request_id="h9"))
        gone = await wait_until_all_dead(pids[2:])
        return first, second, pids, gone

    first, second, pids, gone = with_daemon(rig.paths, run)
    answers = sorted([first["ok"], second["ok"]])
    refused = first if first["ok"] is False else second
    assert answers == [False, True], (first, second)
    assert refused["error"]["code"] == "handover_in_use"
    assert len(pids) == 4 and gone is True
    assert rig.register_lines() == ["deregister browser", "browser", "deregister browser"]


def test_an_engine_that_cannot_start_refuses_the_handover(rig):
    """The session's own start is what fails, so nothing is registered and nothing is left running."""

    async def run():
        rig.paths.chromium_exe.unlink()
        started = await serve.request(rig.paths, _start())
        listing = await serve.request(rig.paths, _op("sessions", request_id="h7"))
        gone = await wait_until_all_dead(rig.display_pids())
        status = await serve.request(rig.paths, _op("handover_status"))
        return started, listing, gone, status, sorted(path.name for path in rig.x11_dir.glob("X*"))

    started, listing, gone, status, sockets = with_daemon(rig.paths, run)
    assert started["ok"] is False and started["error"]["code"] == "engine_unavailable"
    assert [s["state"] for s in listing["data"]["sessions"] if s["name"] == "research"] == ["stopped"]
    assert gone is True and sockets == []
    assert status["data"]["state"] == "inactive"
    assert rig.register_lines() == ["deregister browser"]


def test_a_handover_expires_on_its_own(rig, monkeypatch):
    monkeypatch.setattr(handover, "MINUTE_SECS", 0.5)

    async def run():
        await serve.request(rig.paths, _start(minutes=1))
        deadline = time.monotonic() + EXPIRY_DEADLINE_SECS
        while time.monotonic() < deadline:
            status = await serve.request(rig.paths, _op("handover_status"))
            if status["data"]["state"] == "expired":
                return status
            await asyncio.sleep(POLL_INTERVAL_SECS)
        raise AssertionError("the handover never expired")

    status = with_daemon(rig.paths, run)
    assert status["data"]["state"] == "expired"
    assert rig.keys() == []
    assert rig.register_lines() == ["deregister browser", "browser", "deregister browser"]


def test_a_missing_public_url_fails_before_anything_is_registered(rig, monkeypatch):
    monkeypatch.delenv("VESTAD_PUBLIC_URL")

    async def run():
        started = await serve.request(rig.paths, _start())
        listing = await serve.request(rig.paths, _op("sessions", request_id="h7"))
        return started, listing

    started, listing = with_daemon(rig.paths, run)
    assert started["ok"] is False and started["error"]["code"] == "handover_failed"
    assert "VESTAD_PUBLIC_URL" in started["error"]["message"]
    assert rig.register_lines() == ["deregister browser"]
    assert [s["state"] for s in listing["data"]["sessions"] if s["name"] == "research"] == []


def test_a_mint_failure_rolls_the_whole_handover_back(rig):
    write_script(rig.tmp_path / "bin", "service-key", f"#!{sys.executable}\nimport sys; print('no key', file=sys.stderr); sys.exit(1)\n")

    async def run():
        started = await serve.request(rig.paths, _start())
        pids = rig.display_pids()
        gone = await wait_until_all_dead(pids[2:])
        await wait_for_state(rig.paths, "research", "ready")
        status = await serve.request(rig.paths, _op("handover_status"))
        return started, pids, gone, all(pid_alive(pid) for pid in pids[:2]), status

    started, pids, gone, held, status = with_daemon(rig.paths, run)
    assert started["ok"] is False and started["error"]["code"] == "handover_failed"
    assert "no key" in started["error"]["message"]
    assert len(pids) == 4 and gone is True and held is True
    assert rig.register_lines() == ["deregister browser", "browser", "deregister browser"]
    assert status["data"]["state"] == "failed"


@pytest.mark.parametrize("minutes", [0, 241, True])
def test_a_lifetime_outside_the_allowed_range_is_refused(rig, minutes):
    async def run():
        return await serve.request(rig.paths, _start(minutes=minutes))

    refused = with_daemon(rig.paths, run)
    assert refused["ok"] is False and refused["error"]["code"] == "invalid_request"
    assert rig.register_lines() == ["deregister browser"]


def test_a_shutdown_during_start_leaves_no_display_behind(rig):
    """The daemon stops while the stack is half built: it owns the bring-up, so it takes it back."""
    (rig.x11_dir / "slow").write_text("")

    async def run():
        pending = asyncio.create_task(serve.request(rig.paths, _start()))
        try:
            await wait_for_state(rig.paths, "research", "handed_over")
            await _wait_for_pids(rig, 3)
            browser = int((rig.paths.profiles / "chromium" / "research" / "fake.pid").read_text())
            return await serve.request(rig.paths, _op("handover_status")), rig.display_pids(), browser
        finally:
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending

    status, pids, browser = with_daemon(rig.paths, run)
    assert status["data"]["state"] == "starting" and status["data"]["user_url"] is None
    assert len(pids) == 3 and _await_all_dead([*pids, browser])
    assert rig.register_lines() == ["deregister browser", "browser", "deregister browser"]


def test_daemon_shutdown_stops_a_live_handover(rig):
    async def run():
        started = await serve.request(rig.paths, _start())
        assert started["ok"] is True, started
        browser = int((rig.paths.profiles / "chromium" / "research" / "fake.pid").read_text())
        return rig.display_pids(), browser

    pids, browser = with_daemon(rig.paths, run)
    assert len(pids) == 4 and _await_all_dead([*pids, browser])
    assert rig.keys() == []
    assert rig.register_lines() == ["deregister browser", "browser", "deregister browser"]


def test_a_bring_up_that_outlives_its_budget_fails_and_takes_the_stack_back(rig, monkeypatch):
    """The x11vnc that never binds: the daemon answers inside its own budget, not the engine's."""
    (rig.x11_dir / "hang").write_text("")
    monkeypatch.setattr(handover, "HANDOVER_START_BUDGET_SECS", BUDGET_SECS)

    async def run():
        started = await serve.request(rig.paths, _start())
        pids = rig.display_pids()
        gone = await wait_until_all_dead(pids[2:])
        await wait_for_state(rig.paths, "research", "ready")
        status = await serve.request(rig.paths, _op("handover_status"))
        return started, pids, gone, all(pid_alive(pid) for pid in pids[:2]), status

    started, pids, gone, held, status = with_daemon(rig.paths, run)
    assert started["ok"] is False and started["error"]["code"] == "handover_failed"
    assert f"{BUDGET_SECS}s" in started["error"]["message"]
    assert len(pids) == 3 and gone is True and held is True
    assert rig.register_lines() == ["deregister browser", "browser", "deregister browser"]
    assert status["data"]["state"] == "failed"
