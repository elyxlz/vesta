import asyncio
import os
import pathlib as pl
import socket
import time
import urllib.request

import pytest
from vesta_browser import display
from vesta_browser.procs import KILL_GRACE_SECS, kill_group
from vesta_browser.runtime_paths import load_paths

from .fakes import write_display_fakes

PID_POLL_SECS = 0.05
PID_GONE_TIMEOUT_SECS = 10.0
HTTP_TIMEOUT_SECS = 5
WEB_PORT_FIRST = 6080
# Above DISPLAY_LAST, so no real claim and no other test can be holding this abstract name.
ABSTRACT_ONLY_DISPLAY = 1234


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """Paths whose X socket dir, noVNC tree, and four binaries all sit under tmp_path."""
    bin_dir = tmp_path / "bin"
    x11_dir = tmp_path / "x"
    write_display_fakes(bin_dir, x11_dir)
    novnc = tmp_path / "novnc"
    (novnc / "core").mkdir(parents=True)
    (novnc / "core" / "rfb.js").write_text("export default class RFB {}\n")
    (novnc / "vendor").mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    return load_paths({"VESTA_BROWSER_NOVNC_DIR": str(novnc), "VESTA_BROWSER_X11_DIR": str(x11_dir)}, tmp_path)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _await_gone(pids: list[int]) -> bool:
    deadline = time.monotonic() + PID_GONE_TIMEOUT_SECS
    while time.monotonic() < deadline:
        if not any(_alive(pid) for pid in pids):
            return True
        time.sleep(PID_POLL_SECS)
    return not any(_alive(pid) for pid in pids)


def _listening_x_socket(path: pl.Path) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    sock.listen(8)
    return sock


def _cmdline(pid: int) -> list[str]:
    return pl.Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0")


def _fetch(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SECS) as answer:
        return answer.status, answer.read().decode()


async def _full_stack(paths) -> display.DisplayStack:
    """Every piece of a live handover display, torn back down if any later piece fails."""
    started: list[asyncio.subprocess.Process] = []
    try:
        display_name, xvfb = await display.claim_display(paths)
        started.append(xvfb)
        openbox = await display.start_openbox(paths, display_name)
        started.append(openbox)
        vnc_port = display.free_port(display.VNC_PORT_FIRST)
        x11vnc = await display.start_x11vnc(display_name, vnc_port)
        started.append(x11vnc)
        webroot = display.build_webroot(paths)
        web_port = display.free_port(WEB_PORT_FIRST)
        websockify = await display.start_websockify(webroot, web_port, vnc_port, paths.log)
    except Exception:
        for process in reversed(started):
            await kill_group(process, KILL_GRACE_SECS)
        raise
    return display.DisplayStack(
        display=display_name,
        xvfb=xvfb,
        openbox=openbox,
        x11vnc=x11vnc,
        websockify=websockify,
        vnc_port=vnc_port,
        web_port=web_port,
        webroot=webroot,
    )


def test_readiness_reports_every_missing_piece(tmp_path, monkeypatch):
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    paths = load_paths({"VESTA_BROWSER_NOVNC_DIR": str(tmp_path / "novnc")}, tmp_path)
    assert display.readiness(paths) == {"ready": False, "missing": ["Xvfb", "x11vnc", "websockify", "openbox", "novnc"]}


def test_readiness_is_ready_once_the_binaries_and_novnc_are_there(rig):
    assert display.readiness(rig) == {"ready": True, "missing": []}


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
            return process.pid, _cmdline(process.pid), display.port_serving(port)
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
    with pytest.raises(display.DisplayError, match="noVNC"):
        display.build_webroot(rig)


def test_websockify_serves_the_page_on_its_port(rig):
    webroot = display.build_webroot(rig)
    port = display.free_port(WEB_PORT_FIRST)

    async def run():
        process = await display.start_websockify(webroot, port, 5999, rig.log)
        try:
            return process.pid, await asyncio.to_thread(_fetch, f"http://127.0.0.1:{port}/handover.html")
        finally:
            await kill_group(process, KILL_GRACE_SECS)

    pid, (status, body) = asyncio.run(run())
    assert status == 200 and "websockify" in body
    assert _await_gone([pid])


def test_stop_stack_ends_every_process_and_clears_the_socket(rig):
    async def run():
        stack = await _full_stack(rig)
        pids = [stack.xvfb.pid, stack.openbox.pid, stack.x11vnc.pid, stack.websockify.pid]
        try:
            serving = display.port_serving(stack.web_port) and display.port_serving(stack.vnc_port)
            await display.stop_stack(rig, stack)
        finally:
            for process in (stack.websockify, stack.x11vnc, stack.openbox, stack.xvfb):
                if process.returncode is None:
                    await kill_group(process, KILL_GRACE_SECS)
        return stack.display, pids, serving

    name, pids, serving = asyncio.run(run())
    assert serving
    assert _await_gone(pids)
    assert not (rig.x11_socket_dir / f"X{name.lstrip(':')}").exists()
