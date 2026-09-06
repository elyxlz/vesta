import asyncio
import pathlib as pl
import shutil
import socket
import sys

import pytest
from vesta_browser import display
from vesta_browser.procs import KILL_GRACE_SECS, kill_group
from vesta_browser.runtime_paths import load_paths

from .hermetic import display_rig
from .waiting import cmdline_of, fetch, pid_alive, wait_for_recorded_pids, wait_until_all_dead

PID_GONE_TIMEOUT_SECS = 10.0
WEB_PORT_FIRST = 6080
# Above DISPLAY_LAST, so no real claim and no other test can be holding this abstract name.
ABSTRACT_ONLY_DISPLAY = 1234


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """Paths whose noVNC tree and four binaries sit under tmp_path, with the X sockets under /tmp."""
    env, x11_dir = display_rig(tmp_path, monkeypatch, novnc=True, camoufox=False)
    yield load_paths(env, tmp_path)
    shutil.rmtree(x11_dir, ignore_errors=True)


def _await_gone(pids: list[int]) -> bool:
    return asyncio.run(wait_until_all_dead(pids, PID_GONE_TIMEOUT_SECS))


def _listening_x_socket(path: pl.Path) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    sock.listen(8)
    return sock


async def _full_stack(paths) -> tuple[display.SessionDisplay, display.StreamStack]:
    """A live session display plus the stream on it, torn back down if any later piece fails."""
    session_display = await display.start_session_display(paths)
    started: list[asyncio.subprocess.Process] = []
    try:
        vnc_port = display.free_port(display.VNC_PORT_FIRST)
        x11vnc = await display.start_x11vnc(session_display.display, vnc_port)
        started.append(x11vnc)
        webroot = display.build_webroot(paths)
        web_port = display.free_port(WEB_PORT_FIRST)
        websockify = await display.start_websockify(webroot, web_port, vnc_port, paths.log)
    except Exception:
        for process in reversed(started):
            await kill_group(process, KILL_GRACE_SECS)
        await display.stop_session_display(paths, session_display)
        raise
    stack = display.StreamStack(x11vnc=x11vnc, websockify=websockify, vnc_port=vnc_port, web_port=web_port, webroot=webroot)
    return session_display, stack


def test_display_readiness_reports_missing_binaries(tmp_path, monkeypatch):
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert display.display_readiness() == {"ready": False, "missing": ["Xvfb", "openbox"]}


def test_stream_readiness_reports_missing_binaries_and_novnc(tmp_path, monkeypatch):
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    paths = load_paths({"VESTA_BROWSER_NOVNC_DIR": str(tmp_path / "novnc")}, tmp_path)
    assert display.stream_readiness(paths) == {"ready": False, "missing": ["x11vnc", "websockify", "novnc"]}


def test_display_readiness_is_ready_with_the_fakes(rig):
    assert display.display_readiness() == {"ready": True, "missing": []}


def test_stream_readiness_is_ready_with_the_fakes_and_novnc(rig):
    assert display.stream_readiness(rig) == {"ready": True, "missing": []}


def test_display_reachable_sees_a_server_holding_only_the_abstract_socket(rig):
    number = ABSTRACT_ONLY_DISPLAY
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        try:
            sock.bind(f"{display.ABSTRACT_X11_PREFIX}{number}")
        except PermissionError:
            pytest.skip("this kernel refuses a bind in the abstract namespace")
        sock.listen(8)
        assert display.display_reachable(rig, number)
        assert not display.own_display_serving(rig, number)
    finally:
        sock.close()


def test_an_exited_xvfb_is_not_ready_while_another_socket_answers(rig):
    """Readiness reads the process before the socket, so a dead Xvfb never passes on someone else's."""
    number = ABSTRACT_ONLY_DISPLAY
    held = _listening_x_socket(rig.x11_socket_dir / f"X{number}")

    async def run():
        process = await asyncio.create_subprocess_exec(sys.executable, "-c", "raise SystemExit(1)")
        await process.wait()
        return await display._xvfb_ready(rig, process, number)

    try:
        ready = asyncio.run(run())
    finally:
        held.close()
    assert ready is False


def test_claim_display_returns_a_display_this_container_serves(rig):
    async def run():
        name, xvfb = await display.claim_display(rig)
        try:
            return name, xvfb.pid, display.own_display_serving(rig, int(name.lstrip(":")))
        finally:
            await kill_group(xvfb, KILL_GRACE_SECS)

    name, pid, serving = asyncio.run(run())
    assert name == f":{display.DISPLAY_FIRST}" and serving
    assert (rig.x11_socket_dir / f"X{display.DISPLAY_FIRST}").exists()
    assert _await_gone([pid])


def test_claim_display_skips_a_number_someone_else_serves(rig):
    held = _listening_x_socket(rig.x11_socket_dir / f"X{display.DISPLAY_FIRST}")

    async def run():
        name, xvfb = await display.claim_display(rig)
        try:
            return name, xvfb.pid
        finally:
            await kill_group(xvfb, KILL_GRACE_SECS)

    try:
        name, pid = asyncio.run(run())
    finally:
        held.close()
    assert name == f":{display.DISPLAY_FIRST + 1}"
    assert _await_gone([pid])


def test_x11vnc_argv_carries_the_port_the_cursor_and_the_shm_choice():
    plain = display.x11vnc_argv(":99", 5900, noshm=False)
    assert plain[:6] == ["x11vnc", "-display", ":99", "-localhost", "-rfbport", "5900"]
    assert "-cursorpos" in plain and "-threads" in plain and "-noshm" not in plain
    assert display.x11vnc_argv(":99", 5900, noshm=True)[-1] == "-noshm"


def test_x11vnc_retries_without_shm_when_the_first_attempt_dies(rig):
    (rig.x11_socket_dir / "fail-shm").write_text("")
    port = display.free_port(display.VNC_PORT_FIRST)

    async def run():
        process = await display.start_x11vnc(":99", port)
        try:
            return process.pid, cmdline_of(process.pid), display.port_serving(port)
        finally:
            await kill_group(process, KILL_GRACE_SECS)

    pid, argv, serving = asyncio.run(run())
    assert serving and "-noshm" in argv
    assert _await_gone([pid])


def test_x11vnc_that_never_serves_raises(rig):
    (rig.x11_socket_dir / "fail-always").write_text("")
    with pytest.raises(display.DisplayError, match="x11vnc"):
        asyncio.run(display.start_x11vnc(":99", display.free_port(display.VNC_PORT_FIRST)))


def test_build_webroot_lays_out_the_page_the_fonts_and_novnc(rig):
    webroot = display.build_webroot(rig)
    assert webroot == rig.handover_web
    assert "RFB" in (webroot / "handover.html").read_text()
    assert (webroot / "fonts" / "public-sans.woff2").is_file()
    assert (webroot / "macbook.png").is_file()
    assert (webroot / "core").is_symlink() and (webroot / "vendor").is_symlink()
    assert (webroot / "core" / "rfb.js").is_file()


def test_build_webroot_replaces_whatever_was_there(rig):
    display.build_webroot(rig)
    (rig.handover_web / "stale.txt").write_text("old")
    display.build_webroot(rig)
    assert not (rig.handover_web / "stale.txt").exists()


def test_build_webroot_without_novnc_raises(rig):
    (rig.novnc_dir / "core" / "rfb.js").unlink()
    with pytest.raises(display.DisplayError, match="novnc"):
        display.build_webroot(rig)


def test_websockify_serves_the_page_on_its_port(rig):
    webroot = display.build_webroot(rig)
    port = display.free_port(WEB_PORT_FIRST)

    async def run():
        process = await display.start_websockify(webroot, port, 5999, rig.log)
        try:
            page = await asyncio.to_thread(fetch, f"http://127.0.0.1:{port}/handover.html")
            return process.pid, cmdline_of(process.pid), page
        finally:
            await kill_group(process, KILL_GRACE_SECS)

    pid, argv, (status, body) = asyncio.run(run())
    assert status == 200 and "websockify" in body
    # Bound on every interface, not on loopback: vestad proxies the page from outside this container.
    assert f"0.0.0.0:{port}" in argv
    assert _await_gone([pid])


def test_websockify_refuses_a_port_something_else_already_serves(rig):
    """A bridge a killed daemon left behind answers on the port vestad hands out again; a new
    websockify would die on the bind while the port probe read the stranger as ready."""
    webroot = display.build_webroot(rig)
    port = display.free_port(WEB_PORT_FIRST)
    squatter = socket.socket()
    squatter.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    squatter.bind(("127.0.0.1", port))
    squatter.listen(1)
    try:
        with pytest.raises(display.DisplayError, match="does not own"):
            asyncio.run(display.start_websockify(webroot, port, 5999, rig.log))
    finally:
        squatter.close()
    assert not (rig.x11_socket_dir / "pids").exists()


def test_start_session_display_returns_a_display_this_container_serves(rig):
    pids_file = rig.x11_socket_dir / "pids"

    async def run():
        session_display = await display.start_session_display(rig)
        try:
            serving = display.own_display_serving(rig, display.display_number(session_display.display))
            await wait_for_recorded_pids(pids_file, 2, PID_GONE_TIMEOUT_SECS)
            return session_display, serving
        finally:
            await display.stop_session_display(rig, session_display)

    session_display, serving = asyncio.run(run())
    assert session_display.display == f":{display.DISPLAY_FIRST}" and serving
    pids = sorted(int(line) for line in pids_file.read_text().split())
    assert pids == sorted([session_display.xvfb.pid, session_display.openbox.pid])
    assert _await_gone(pids)


def _capturing_claim_display(captured: dict[str, object], ready: asyncio.Event | None = None):
    """Wraps the real `claim_display` so a test can read the display name and Xvfb pid it started
    even when the call that follows never returns one, and can wait on `ready` for that moment."""
    real_claim_display = display.claim_display

    async def claim(paths):
        name, xvfb = await real_claim_display(paths)
        captured["display"] = name
        captured["pid"] = xvfb.pid
        if ready is not None:
            ready.set()
        return name, xvfb

    return claim


def test_start_session_display_kills_xvfb_when_openbox_cannot_spawn(rig, monkeypatch):
    captured: dict[str, object] = {}

    async def _openbox_raises(_paths, _display_name):
        raise OSError("no openbox binary")

    monkeypatch.setattr(display, "claim_display", _capturing_claim_display(captured))
    monkeypatch.setattr(display, "start_openbox", _openbox_raises)

    async def run():
        with pytest.raises(display.DisplayError, match="openbox"):
            await display.start_session_display(rig)

    asyncio.run(run())
    assert _await_gone([captured["pid"]])
    assert not (rig.x11_socket_dir / f"X{captured['display'].lstrip(':')}").exists()


def test_start_session_display_kills_xvfb_when_cancelled_before_openbox_starts(rig, monkeypatch):
    captured: dict[str, object] = {}
    xvfb_claimed = asyncio.Event()

    async def _openbox_hangs(_paths, _display_name):
        await asyncio.Event().wait()

    monkeypatch.setattr(display, "claim_display", _capturing_claim_display(captured, xvfb_claimed))
    monkeypatch.setattr(display, "start_openbox", _openbox_hangs)

    async def run():
        task = asyncio.create_task(display.start_session_display(rig))
        await asyncio.wait_for(xvfb_claimed.wait(), PID_GONE_TIMEOUT_SECS)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert _await_gone([captured["pid"]])
    assert not (rig.x11_socket_dir / f"X{captured['display'].lstrip(':')}").exists()


def test_stop_session_display_ends_both_and_clears_the_socket(rig):
    async def run():
        session_display = await display.start_session_display(rig)
        pids = [session_display.xvfb.pid, session_display.openbox.pid]
        await display.stop_session_display(rig, session_display)
        return session_display.display, pids

    name, pids = asyncio.run(run())
    assert _await_gone(pids)
    assert not (rig.x11_socket_dir / f"X{name.lstrip(':')}").exists()


def test_stop_stack_ends_the_stream_and_leaves_the_display_alive(rig):
    async def run():
        session_display, stack = await _full_stack(rig)
        stream_pids = [stack.x11vnc.pid, stack.websockify.pid]
        display_pids = [session_display.xvfb.pid, session_display.openbox.pid]
        serving = display.port_serving(stack.web_port) and display.port_serving(stack.vnc_port)
        await display.stop_stack(stack)
        stream_gone = await wait_until_all_dead(stream_pids, PID_GONE_TIMEOUT_SECS)
        display_still_alive = all(pid_alive(pid) for pid in display_pids)
        await display.stop_session_display(rig, session_display)
        return serving, stream_gone, display_still_alive, display_pids

    serving, stream_gone, display_still_alive, display_pids = asyncio.run(run())
    assert serving and stream_gone and display_still_alive
    assert _await_gone(display_pids)
