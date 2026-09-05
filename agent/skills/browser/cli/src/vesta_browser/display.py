"""The X display a handover streams from: an Xvfb this container owns, a window manager, x11vnc, and
websockify serving the noVNC page.

The display is always a fresh Xvfb, never the ambient one: x11vnc cannot X_GetImage a live desktop
seat (it fails BadMatch and the page then spins forever), and a desktop's own DISPLAY would render
the headed browser onto the user's monitor. An X server listens on two sockets, an abstract one
scoped to the whole network namespace and a filesystem one under this container's own /tmp, and
Xlib prefers the abstract one. A display number is therefore free only when neither socket answers,
while proof that the server on it is ours comes from the filesystem socket alone.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import os
import pathlib as pl
import shutil
import socket
import time

from . import protocol as p
from .procs import KILL_GRACE_SECS, kill_group
from .runtime_paths import Paths

# The 13" MacBook's native resolution: a real monitor size, and the one the framed machine in the
# page has. A geometry no real display ships would itself be an automation tell on the
# account-trust sites a handover exists for.
SCREEN_W, SCREEN_H = 1280, 800
DISPLAY_FIRST, DISPLAY_LAST = 99, 198
DISPLAY_CLAIM_ATTEMPTS = 10
VNC_PORT_FIRST = 5900
PORT_SCAN_SPAN = 200
XVFB_READY_TIMEOUT_SECS = 5.0
X11VNC_READY_TIMEOUT_SECS = 10.0
X11VNC_SETTLE_SECS = 0.4
WEB_READY_TIMEOUT_SECS = 10.0
READY_POLL_SECS = 0.2
SOCKET_PROBE_TIMEOUT_SECS = 2.0
HANDOVER_BINARIES = ("Xvfb", "x11vnc", "websockify", "openbox")
HANDOVER_APT_LINE = "apt-get install -y xvfb novnc x11vnc openbox"
DEFAULT_X11_SOCKET_DIR = pl.Path("/tmp/.X11-unix")
ABSTRACT_X11_PREFIX = "\0/tmp/.X11-unix/X"

# The handover display shows exactly one window. Left to itself openbox smart-places it a few pixels
# off origin and adds a titlebar, so the stream sits misaligned in the page's screen cut-out.
OPENBOX_RC = """<?xml version="1.0"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <applications>
    <application class="*">
      <decor>no</decor>
      <position force="yes"><x>0</x><y>0</y></position>
      <maximized>yes</maximized>
    </application>
  </applications>
</openbox_config>
"""


class DisplayError(Exception):
    """A piece of the display stack is missing, lost its race, or never came up."""


@dataclasses.dataclass
class DisplayStack:
    display: str
    xvfb: asyncio.subprocess.Process
    openbox: asyncio.subprocess.Process
    x11vnc: asyncio.subprocess.Process
    websockify: asyncio.subprocess.Process
    vnc_port: int
    web_port: int
    webroot: pl.Path


def _path() -> str:
    return os.environ["PATH"] if "PATH" in os.environ else "/usr/local/bin:/usr/bin:/bin"


def _base_env() -> dict[str, str]:
    return {"PATH": _path(), "HOME": str(pl.Path.home())}


def child_env(display: str) -> dict[str, str]:
    """The env of every X client here: our display, and Firefox forced onto X11.

    x11vnc 0.9.x exits outright when WAYLAND_DISPLAY is set and Gecko prefers a Wayland session over
    the X display we just claimed, so the env is built from nothing rather than inherited.
    """
    return {**_base_env(), "DISPLAY": display, "MOZ_ENABLE_WAYLAND": "0"}


def readiness(paths: Paths) -> dict[str, p.JsonValue]:
    """Whether every handover prerequisite is installed, so `doctor` names the gap up front."""
    missing = [name for name in HANDOVER_BINARIES if shutil.which(name) is None]
    if not (paths.novnc_dir / "core" / "rfb.js").is_file():
        missing.append("novnc")
    return {"ready": not missing, "missing": list(missing)}


def _unix_socket_serving(address: str) -> bool:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(SOCKET_PROBE_TIMEOUT_SECS)
    try:
        sock.connect(address)
    except OSError:
        return False
    else:
        return True
    finally:
        sock.close()


def own_display_serving(paths: Paths, number: int) -> bool:
    """Whether OUR Xvfb holds `number`: the filesystem socket is created by this container alone."""
    return _unix_socket_serving(str(paths.x11_socket_dir / f"X{number}"))


def display_reachable(paths: Paths, number: int) -> bool:
    """Whether any X server in this network namespace serves `number`, ours or a stranger's."""
    return _unix_socket_serving(f"{ABSTRACT_X11_PREFIX}{number}") or own_display_serving(paths, number)


def port_serving(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(SOCKET_PROBE_TIMEOUT_SECS)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def free_port(first: int) -> int:
    for port in range(first, first + PORT_SCAN_SPAN):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise DisplayError(f"no free port in {first}-{first + PORT_SCAN_SPAN}")


def _free_display_number(paths: Paths, first: int) -> int:
    for number in range(first, DISPLAY_LAST + 1):
        if not display_reachable(paths, number):
            return number
    raise DisplayError(f"no free X display in :{first}-:{DISPLAY_LAST}")


def _clear_stale_records(paths: Paths, number: int) -> None:
    """Drop what a dead Xvfb left on a number nothing is listening on, so the next one can bind it."""
    with contextlib.suppress(OSError):
        (paths.x11_socket_dir / f"X{number}").unlink(missing_ok=True)
    if paths.x11_socket_dir == DEFAULT_X11_SOCKET_DIR:
        with contextlib.suppress(OSError):
            pl.Path(f"/tmp/.X{number}-lock").unlink(missing_ok=True)


async def _xvfb_ready(paths: Paths, process: asyncio.subprocess.Process, number: int) -> bool:
    deadline = time.monotonic() + XVFB_READY_TIMEOUT_SECS
    while time.monotonic() < deadline:
        if await asyncio.to_thread(own_display_serving, paths, number):
            return True
        if process.returncode is not None:
            return False
        await asyncio.sleep(READY_POLL_SECS)
    return False


async def claim_display(paths: Paths) -> tuple[str, asyncio.subprocess.Process]:
    """A display number this container's own Xvfb holds, with the process holding it.

    A scan reports who holds a number the instant it looks, so two claimants in one network namespace
    can pick the same free number and race to bind its abstract socket: the loser's Xvfb dies while
    the winner keeps answering there. Confirming our own filesystem socket is what tells those two
    outcomes apart, and a lost race just advances to the next number.
    """
    number = DISPLAY_FIRST
    for _ in range(DISPLAY_CLAIM_ATTEMPTS):
        number = _free_display_number(paths, number)
        display = f":{number}"
        _clear_stale_records(paths, number)
        process = await asyncio.create_subprocess_exec(
            "Xvfb",
            display,
            "-screen",
            "0",
            f"{SCREEN_W}x{SCREEN_H}x24",
            "-nolisten",
            "tcp",
            env=child_env(display),
            start_new_session=True,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if await _xvfb_ready(paths, process, number):
            return display, process
        if process.returncode is None:
            await kill_group(process, KILL_GRACE_SECS)
        number += 1
    raise DisplayError(f"could not claim an X display in {DISPLAY_CLAIM_ATTEMPTS} attempts")


async def start_openbox(paths: Paths, display: str) -> asyncio.subprocess.Process:
    rc_path = paths.handover_web / "openbox-rc.xml"
    rc_path.parent.mkdir(parents=True, exist_ok=True)
    rc_path.write_text(OPENBOX_RC)
    return await asyncio.create_subprocess_exec(
        "openbox",
        "--config-file",
        str(rc_path),
        env=child_env(display),
        start_new_session=True,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )


def x11vnc_argv(display: str, vnc_port: int, *, noshm: bool) -> list[str]:
    """-cursor most and -cursorpos send the real X cursor shape and position, not a static dot;
    XDAMAGE (left on) re-encodes only changed regions and -threads parallelises the encoding."""
    argv = ["x11vnc", "-display", display, "-localhost", "-rfbport", str(vnc_port)]
    argv += ["-forever", "-shared", "-nopw", "-quiet", "-threads", "-cursor", "most", "-cursorpos"]
    return [*argv, "-noshm"] if noshm else argv


async def _await_port(process: asyncio.subprocess.Process, port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.returncode is not None:
            return False
        if await asyncio.to_thread(port_serving, port):
            return True
        await asyncio.sleep(READY_POLL_SECS)
    return False


async def _x11vnc_settles(process: asyncio.subprocess.Process, vnc_port: int) -> bool:
    """Whether `process` reaches a serving port and is still alive a beat later.

    Binding is not survival: x11vnc grabs the framebuffer around the same time it opens the port, so
    a host that refuses shm can kill it either side of the bind. Requiring it to still be up after
    the settle keeps the -noshm retry reachable from both orders.
    """
    if not await _await_port(process, vnc_port, X11VNC_READY_TIMEOUT_SECS):
        return False
    await asyncio.sleep(X11VNC_SETTLE_SECS)
    return process.returncode is None


async def start_x11vnc(display: str, vnc_port: int) -> asyncio.subprocess.Process:
    """x11vnc serving `vnc_port`, with shm first and -noshm as the fallback.

    Shared memory makes the framebuffer reads roughly 25x faster, so it is always tried first; some
    hosts deny X_ShmAttach and x11vnc dies on its first grab there.
    """
    for noshm in (False, True):
        process = await asyncio.create_subprocess_exec(
            *x11vnc_argv(display, vnc_port, noshm=noshm),
            env=child_env(display),
            start_new_session=True,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if await _x11vnc_settles(process, vnc_port):
            return process
        if process.returncode is None:
            await kill_group(process, KILL_GRACE_SECS)
    raise DisplayError(f"x11vnc never served port {vnc_port}, with or without shm")


def build_webroot(paths: Paths) -> pl.Path:
    """The web root websockify serves: the branded page, its fonts and frame, and noVNC's own code."""
    if not (paths.novnc_dir / "core" / "rfb.js").is_file():
        raise DisplayError(f"noVNC has no core/rfb.js under {paths.novnc_dir}. Install it: {HANDOVER_APT_LINE}")
    webroot = paths.handover_web
    if webroot.exists():
        shutil.rmtree(webroot)
    (webroot / "fonts").mkdir(parents=True)
    shutil.copyfile(paths.assets / "handover.html", webroot / "handover.html")
    shutil.copyfile(paths.assets / "fonts" / "public-sans.woff2", webroot / "fonts" / "public-sans.woff2")
    shutil.copyfile(paths.assets / "macbook.png", webroot / "macbook.png")
    for name in ("core", "vendor"):
        source = paths.novnc_dir / name
        if source.is_dir():
            (webroot / name).symlink_to(source)
    return webroot


async def start_websockify(webroot: pl.Path, web_port: int, vnc_port: int, log: pl.Path) -> asyncio.subprocess.Process:
    """The bridge from the page's WebSocket to x11vnc, bound on every interface for vestad to proxy."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as handle:
        process = await asyncio.create_subprocess_exec(
            "websockify",
            "--web",
            str(webroot),
            f"0.0.0.0:{web_port}",
            f"localhost:{vnc_port}",
            env=_base_env(),
            start_new_session=True,
            stdout=handle,
            stderr=asyncio.subprocess.STDOUT,
        )
    if await _await_port(process, web_port, WEB_READY_TIMEOUT_SECS):
        return process
    await kill_group(process, KILL_GRACE_SECS)
    raise DisplayError(f"websockify never served port {web_port}. See {log}")


async def stop_stack(paths: Paths, stack: DisplayStack) -> None:
    """Tear the stack down, Xvfb last: the other three are its clients and would thrash without it."""
    await asyncio.gather(
        kill_group(stack.websockify, KILL_GRACE_SECS),
        kill_group(stack.x11vnc, KILL_GRACE_SECS),
        kill_group(stack.openbox, KILL_GRACE_SECS),
    )
    await kill_group(stack.xvfb, KILL_GRACE_SECS)
    _clear_stale_records(paths, int(stack.display.lstrip(":").split(".")[0]))
