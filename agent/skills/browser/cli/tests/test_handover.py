"""The handover: the session's own display streamed to one keyed URL, and one clean teardown."""

import asyncio
import contextlib
import datetime as dt
import json
import os
import shutil
import signal
import sys
import time

import pytest
from vesta_browser import chromium, display, handover
from vesta_browser import protocol as p
from vesta_browser.runtime_paths import load_paths

from .fakes import display_pids, write_script
from .hermetic import display_rig
from .waiting import (
    POLL_DEADLINE_SECS,
    POLL_INTERVAL_SECS,
    cmdline_of,
    exec_request,
    fetch,
    pid_alive,
    request,
    wait_for_recorded_pids,
    wait_for_state,
    wait_until_all_dead,
    wait_until_dead,
    with_daemon,
)

PUBLIC_URL = "https://gw.example"
AGENT = "luna"
WEB_PORT_FIRST = 6180
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
        return display_pids(self.x11_dir)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    env, x11_dir = display_rig(tmp_path, monkeypatch, novnc=True, camoufox=True)
    web_port = display.free_port(WEB_PORT_FIRST)
    monkeypatch.setenv("FAKE_KEYS", str(tmp_path / "keys.json"))
    monkeypatch.setenv("FAKE_REGISTER_LOG", str(tmp_path / "register.log"))
    monkeypatch.setenv("FAKE_PORT", str(web_port))
    monkeypatch.setenv("VESTAD_PUBLIC_URL", PUBLIC_URL)
    monkeypatch.setenv("AGENT_NAME", AGENT)
    yield Rig(load_paths(env, tmp_path), tmp_path, x11_dir, web_port)
    shutil.rmtree(x11_dir, ignore_errors=True)


def _start(session="research", mode=None, url=None, minutes=None, request_id="h1"):
    return p.request("handover_start", request_id, session=session, mode=mode, url=url, minutes=minutes)


async def _wait_for_pids(rig, wanted):
    await wait_for_recorded_pids(rig.x11_dir / "pids", wanted)


def _minutes_ahead(stamp):
    when = dt.datetime.fromisoformat(stamp)
    return (when - dt.datetime.now(dt.UTC)).total_seconds() / 60


def test_handover_start_serves_the_page_and_hands_the_session_over(rig):
    async def run():
        started = await request(rig.paths, _start(url="https://example.com/"))
        try:
            await _wait_for_pids(rig, 4)
            status = await request(rig.paths, p.request("handover_status", "h2"))
            listing = await request(rig.paths, p.request("sessions", "h3"))
            page, _ = await asyncio.to_thread(fetch, f"http://127.0.0.1:{rig.web_port}/handover.html")
            navigate = (rig.paths.sessions / "research/tmp/code.txt").read_text()
            return started, status, listing, page, rig.register_lines(), navigate, rig.display_pids()
        finally:
            await request(rig.paths, p.request("handover_stop", "h9"))

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
        first = await request(rig.paths, exec_request("research", "print(1)"))
        await _wait_for_pids(rig, 2)
        display_pids = rig.display_pids()
        started = await request(rig.paths, _start())
        await _wait_for_pids(rig, 4)
        stream_pids = rig.display_pids()[len(display_pids) :]
        stopped = await request(rig.paths, p.request("handover_stop", "h2"))
        await wait_for_state(rig.paths, "research", "ready")
        gone = await wait_until_all_dead(stream_pids)
        again = await request(rig.paths, exec_request("research", "print(2)", request_id="e2"))
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
        started = await request(rig.paths, _start(session="stealthy", mode="stealth", minutes=5))
        await _wait_for_pids(rig, 4)
        pids = rig.display_pids()
        launch = json.loads((rig.paths.profiles / "camoufox" / "stealthy" / "launch.json").read_text())
        minted = rig.keys()
        await request(rig.paths, p.request("handover_stop", "h9"))
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
        await request(rig.paths, _start())
        try:
            ran = await request(rig.paths, exec_request("research", "print(1)"))
            stopped = await request(rig.paths, p.request("session_stop", "h4", session="research"))
            again = await request(rig.paths, _start(request_id="h5"))
            return ran, stopped, again
        finally:
            await request(rig.paths, p.request("handover_stop", "h9"))

    ran, stopped, again = with_daemon(rig.paths, run)
    assert ran["ok"] is False and ran["error"]["code"] == "handover_in_use"
    assert stopped["ok"] is False and stopped["error"]["code"] == "invalid_request"
    assert again["ok"] is False and again["error"]["code"] == "handover_in_use"


def test_doctor_never_reports_the_handover_key(rig):
    async def run():
        started = await request(rig.paths, _start())
        try:
            return started, await request(rig.paths, p.request("doctor", "h8"))
        finally:
            await request(rig.paths, p.request("handover_stop", "h9"))

    started, reported = with_daemon(rig.paths, run)
    assert started["ok"] is True and "/k/" in started["data"]["user_url"]
    block = reported["data"]["handover"]
    assert block["state"] == "live" and block["handover_id"] == started["data"]["handover_id"]
    assert "user_url" not in block
    assert "/k/" not in json.dumps(reported)


def test_handover_stop_releases_the_key_the_service_and_the_stream(rig):
    async def run():
        await request(rig.paths, _start())
        await _wait_for_pids(rig, 4)
        pids = rig.display_pids()
        stopped = await request(rig.paths, p.request("handover_stop", "h2"))
        await wait_for_state(rig.paths, "research", "ready")
        gone = await wait_until_all_dead(pids[2:])
        held = all(pid_alive(pid) for pid in pids[:2])
        ran = await request(rig.paths, exec_request("research", "print(1)"))
        status = await request(rig.paths, p.request("handover_status", "h6"))
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
        await request(rig.paths, _start())
        await _wait_for_pids(rig, 4)
        pids = rig.display_pids()
        browser = int((rig.paths.profiles / "chromium" / "research" / "fake.pid").read_text())
        os.kill(browser, signal.SIGKILL)
        reaped = await wait_until_dead(browser)
        stopped = await request(rig.paths, p.request("handover_stop", "h2"))
        await wait_for_state(rig.paths, "research", "stopped")
        gone = await wait_until_all_dead(pids)
        again = await request(rig.paths, exec_request("research", "print(1)"))
        return reaped, stopped, gone, again

    reaped, stopped, gone, again = with_daemon(rig.paths, run)
    assert reaped is True
    assert stopped["ok"] is True and stopped["warnings"] == []
    assert gone is True
    assert again["ok"] is True and again["warnings"] == ["worker_restarted"]


def test_status_on_a_handover_whose_stream_died_reports_failed_with_no_url(rig):
    """The keyed URL prints only while the handover is live: a dead one must not hand out a link."""

    async def run():
        started = await request(rig.paths, _start())
        await _wait_for_pids(rig, 4)
        x11vnc = next(pid for pid in rig.display_pids() if "x11vnc" in cmdline_of(pid))
        os.kill(x11vnc, signal.SIGKILL)
        await wait_until_dead(x11vnc)
        status = await request(rig.paths, p.request("handover_status", "h2"))
        await wait_for_state(rig.paths, "research", "ready")
        return started, status

    started, status = with_daemon(rig.paths, run)
    assert started["data"]["user_url"] is not None
    assert status["data"]["state"] == "failed" and status["data"]["user_url"] is None


def test_a_navigation_that_kills_the_browser_fails_before_a_key_is_minted(rig, monkeypatch):
    """Camoufox answers an overlong navigation by killing its worker; the health gate runs before
    the mint, so a key is never made for a browser that is gone."""
    monkeypatch.setattr(handover, "NAVIGATE_TIMEOUT_SECS", 1)

    async def run():
        res = await request(rig.paths, _start(mode="stealth", url="https://slow.example/"))
        await wait_for_state(rig.paths, "research", "stopped")
        return res

    res = with_daemon(rig.paths, run)
    assert res["ok"] is False and res["error"]["code"] == "handover_failed"
    assert "not serving" in res["error"]["message"]
    assert rig.keys() == []


def test_a_handover_without_a_stream_binary_names_the_install_hint(rig):
    """The stream refuses to spawn onto a gap it names, and the route it registered comes back off."""
    (rig.tmp_path / "bin" / "x11vnc").unlink()

    async def run():
        started = await request(rig.paths, _start())
        await wait_for_state(rig.paths, "research", "ready")
        return started

    started = with_daemon(rig.paths, run)
    assert started["ok"] is False and started["error"]["code"] == "handover_failed"
    assert "x11vnc" in started["error"]["message"] and display.INSTALL_HINT in started["error"]["message"]
    assert rig.register_lines() == ["deregister browser", "browser", "deregister browser"]


def test_a_start_whose_engine_never_comes_up_fails_inside_the_one_budget(rig, monkeypatch):
    """The engine start is inside the budget the client waits behind, not beside it."""
    profile = rig.paths.profiles / "chromium" / "research"
    profile.mkdir(parents=True)
    (profile / "no-port").write_text("")
    monkeypatch.setattr(handover, "HANDOVER_START_BUDGET_SECS", BUDGET_SECS)

    async def run():
        began = time.monotonic()
        started = await request(rig.paths, _start())
        elapsed = time.monotonic() - began
        listing = await request(rig.paths, p.request("sessions", "h7"))
        gone = await wait_until_all_dead(rig.display_pids())
        status = await request(rig.paths, p.request("handover_status", "h2"))
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
            request(rig.paths, _start(session="one", request_id="h1")),
            request(rig.paths, _start(session="two", request_id="h2")),
        )
        pids = rig.display_pids()
        await request(rig.paths, p.request("handover_stop", "h9"))
        gone = await wait_until_all_dead(pids[2:])
        return first, second, pids, gone

    first, second, pids, gone = with_daemon(rig.paths, run)
    outcomes = sorted("ok" if answer["ok"] else answer["error"]["code"] for answer in (first, second))
    assert outcomes == ["handover_in_use", "ok"], (first, second)
    assert len(pids) == 4 and gone is True
    assert rig.register_lines() == ["deregister browser", "browser", "deregister browser"]


def test_a_stop_while_the_engine_starts_is_refused_and_the_start_still_lands(rig, monkeypatch):
    """A handover still claiming its browser has nothing to tear down, so the stop waits its turn."""
    launching = asyncio.Event()
    release = asyncio.Event()
    engine_start = chromium.start

    async def _held_start(session, paths, *, headed):
        launching.set()
        await release.wait()
        return await engine_start(session, paths, headed=headed)

    monkeypatch.setattr(chromium, "start", _held_start)

    async def run():
        pending = asyncio.create_task(request(rig.paths, _start()))
        await asyncio.wait_for(launching.wait(), POLL_DEADLINE_SECS)
        refused = await request(rig.paths, p.request("handover_stop", "h2"))
        release.set()
        started = await pending
        await _wait_for_pids(rig, 4)
        pids = rig.display_pids()
        stopped = await request(rig.paths, p.request("handover_stop", "h9"))
        await wait_for_state(rig.paths, "research", "ready")
        gone = await wait_until_all_dead(pids[2:])
        return refused, started, stopped, pids, gone, all(pid_alive(pid) for pid in pids[:2])

    refused, started, stopped, pids, gone, held = with_daemon(rig.paths, run)
    assert refused["ok"] is False and refused["error"]["code"] == "handover_in_use"
    assert started["ok"] is True and started["data"]["state"] == "live", started
    assert stopped["ok"] is True and stopped["warnings"] == []
    assert len(pids) == 4 and gone is True and held is True


def test_an_engine_that_cannot_start_refuses_the_handover(rig):
    """The session's own start is what fails, so nothing is registered and nothing is left running."""

    async def run():
        rig.paths.chromium_exe.unlink()
        started = await request(rig.paths, _start())
        listing = await request(rig.paths, p.request("sessions", "h7"))
        gone = await wait_until_all_dead(rig.display_pids())
        status = await request(rig.paths, p.request("handover_status", "h2"))
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
        await request(rig.paths, _start(minutes=1))
        deadline = time.monotonic() + EXPIRY_DEADLINE_SECS
        while time.monotonic() < deadline:
            status = await request(rig.paths, p.request("handover_status", "h2"))
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
        started = await request(rig.paths, _start())
        listing = await request(rig.paths, p.request("sessions", "h7"))
        return started, listing

    started, listing = with_daemon(rig.paths, run)
    assert started["ok"] is False and started["error"]["code"] == "handover_failed"
    assert "VESTAD_PUBLIC_URL" in started["error"]["message"]
    assert rig.register_lines() == ["deregister browser"]
    assert [s["state"] for s in listing["data"]["sessions"] if s["name"] == "research"] == []


def test_a_mint_failure_rolls_the_whole_handover_back(rig):
    write_script(rig.tmp_path / "bin", "service-key", f"#!{sys.executable}\nimport sys; print('no key', file=sys.stderr); sys.exit(1)\n")

    async def run():
        started = await request(rig.paths, _start())
        pids = rig.display_pids()
        gone = await wait_until_all_dead(pids[2:])
        await wait_for_state(rig.paths, "research", "ready")
        status = await request(rig.paths, p.request("handover_status", "h2"))
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
        return await request(rig.paths, _start(minutes=minutes))

    refused = with_daemon(rig.paths, run)
    assert refused["ok"] is False and refused["error"]["code"] == "invalid_request"
    assert rig.register_lines() == ["deregister browser"]


def test_a_shutdown_during_start_leaves_no_display_behind(rig):
    """The daemon stops while the stack is half built: it owns the bring-up, so it takes it back."""
    (rig.x11_dir / "slow").write_text("")

    async def run():
        pending = asyncio.create_task(request(rig.paths, _start()))
        try:
            await wait_for_state(rig.paths, "research", "handed_over")
            await _wait_for_pids(rig, 3)
            browser = int((rig.paths.profiles / "chromium" / "research" / "fake.pid").read_text())
            return await request(rig.paths, p.request("handover_status", "h2")), rig.display_pids(), browser
        finally:
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending

    status, pids, browser = with_daemon(rig.paths, run)
    assert status["data"]["state"] == "starting" and status["data"]["user_url"] is None
    assert len(pids) == 3 and asyncio.run(wait_until_all_dead([*pids, browser], EXPIRY_DEADLINE_SECS))
    assert rig.register_lines() == ["deregister browser", "browser", "deregister browser"]


def test_daemon_shutdown_stops_a_live_handover(rig):
    async def run():
        started = await request(rig.paths, _start())
        assert started["ok"] is True, started
        browser = int((rig.paths.profiles / "chromium" / "research" / "fake.pid").read_text())
        return rig.display_pids(), browser

    pids, browser = with_daemon(rig.paths, run)
    assert len(pids) == 4 and asyncio.run(wait_until_all_dead([*pids, browser], EXPIRY_DEADLINE_SECS))
    assert rig.keys() == []
    assert rig.register_lines() == ["deregister browser", "browser", "deregister browser"]


def test_a_bring_up_that_outlives_its_budget_fails_and_takes_the_stack_back(rig, monkeypatch):
    """The x11vnc that never binds: the daemon answers inside its own budget, not the engine's."""
    (rig.x11_dir / "hang").write_text("")
    monkeypatch.setattr(handover, "HANDOVER_START_BUDGET_SECS", BUDGET_SECS)

    async def run():
        started = await request(rig.paths, _start())
        pids = rig.display_pids()
        gone = await wait_until_all_dead(pids[2:])
        await wait_for_state(rig.paths, "research", "ready")
        status = await request(rig.paths, p.request("handover_status", "h2"))
        return started, pids, gone, all(pid_alive(pid) for pid in pids[:2]), status

    started, pids, gone, held, status = with_daemon(rig.paths, run)
    assert started["ok"] is False and started["error"]["code"] == "handover_failed"
    assert f"{BUDGET_SECS}s" in started["error"]["message"]
    assert len(pids) == 3 and gone is True and held is True
    assert rig.register_lines() == ["deregister browser", "browser", "deregister browser"]
    assert status["data"]["state"] == "failed"
