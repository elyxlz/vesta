"""The session starter honouring a stop asked for while its browser was still coming up."""

import asyncio
import shutil

import pytest
from vesta_browser import chromium, serve, session_control, sessions
from vesta_browser import protocol as p
from vesta_browser.runtime_paths import load_paths

from .fakes import display_pids
from .hermetic import display_rig
from .waiting import wait_until_all_dead


@pytest.fixture
def paths(tmp_path, monkeypatch):
    env, x11_dir = display_rig(tmp_path, monkeypatch, novnc=False, camoufox=False)
    yield load_paths(env, tmp_path)
    shutil.rmtree(x11_dir, ignore_errors=True)


def test_ensure_running_stops_what_it_started_when_a_stop_was_requested(paths, monkeypatch):
    engine_start = chromium.start

    async def _flag_then_start(session, engine_paths, *, headed):
        session.stop_requested = True
        return await engine_start(session, engine_paths, headed=headed)

    monkeypatch.setattr(chromium, "start", _flag_then_start)

    async def run():
        state = serve.State(paths=paths, table=sessions.load_table(paths))
        session = sessions.resolve_session(state.table, "research", None)
        with pytest.raises(p.BrowserError) as excinfo:
            await session_control.ensure_running(state, session)
        browser = int((session.profile_dir / "fake.pid").read_text())
        dead = await wait_until_all_dead([browser, *display_pids(paths.x11_socket_dir)])
        return excinfo.value.err, session, dead

    err, session, dead = asyncio.run(run())
    assert err["code"] == "cancelled" and err["phase"] == "routing" and err["retryable"] is True
    assert "while its browser was starting" in err["message"]
    assert session.state == "stopped" and session.runtime is None and session.display is None
    assert session.stop_requested is False and session.restart_pending is False
    assert dead is True


def test_a_start_that_fails_clears_a_pending_stop_request(paths, monkeypatch):
    async def _flag_then_fail(session, _paths, *, headed):
        session.stop_requested = True
        raise RuntimeError("no browser")

    monkeypatch.setattr(chromium, "start", _flag_then_fail)

    async def run():
        state = serve.State(paths=paths, table=sessions.load_table(paths))
        session = sessions.resolve_session(state.table, "research", None)
        with pytest.raises(RuntimeError, match="no browser"):
            await session_control.ensure_running(state, session)
        dead = await wait_until_all_dead(display_pids(paths.x11_socket_dir))
        return session, dead

    session, dead = asyncio.run(run())
    assert session.state == "stopped" and session.stop_requested is False
    assert dead is True
