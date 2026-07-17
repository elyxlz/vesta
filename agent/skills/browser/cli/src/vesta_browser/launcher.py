"""Lazily fetch, verify, and launch Camoufox; drive it over WebDriver BiDi.

Camoufox is a recompiled Firefox that spoofs its fingerprint in C++ below JS, so
headless is fully stealthy (no Xvfb, no HeadlessChrome-style UA leak that stock
Chromium needs a real display to hide). We fetch the pinned release on first launch,
verify its sha256, and cache the extracted browser under ~/.cache/camoufox/<tag>/.
The fingerprint comes from a seed-selected preset exported as CAMOU_CONFIG_* env
vars (presets.py). Camoufox announces its BiDi WebSocket once on stderr and offers
no HTTP rediscovery endpoint (unlike CDP's /json/version), so we log stderr to a
file the detached process can always write to and tail it for the URL.
"""

from __future__ import annotations

import contextlib
import os
import platform
import re
import shutil
import socket
import subprocess
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .presets import camou_config_env, fit_to_screen, select_preset

CAMOUFOX_RELEASE_TAG = "v150.0.2-beta.25"
# arm64 and x86_64 assets carry different build numbers within one release, so pin
# each arch's exact asset name + digest rather than templating from a version string.
CAMOUFOX_ASSETS = {
    "aarch64": ("camoufox-150.0.2-alpha.25-lin.arm64.zip", "b2870af8cd99721d41bd48f0cce0f949449ab75364b80ee3d389bd35953ea213"),
    "x86_64": ("camoufox-150.0.2-alpha.26-lin.x86_64.zip", "b146b98b0c2c41023716feef36451f319a534309f72c54584a4b0b88670f510b"),
}
RELEASE_DOWNLOAD_URL = "https://github.com/daijro/camoufox/releases/download"
CACHE_ROOT = Path.home() / ".cache" / "camoufox"
PROFILE_ROOT = Path.home() / ".browser" / "profile"

DOWNLOAD_TIMEOUT_S = 600.0
DOWNLOAD_CHUNK = 1 << 20
READY_TIMEOUT_S = 45.0
READY_POLL_S = 0.2
BIDI_RE = re.compile(r"WebDriver BiDi listening on (ws://\S+)")


@dataclass
class RunningCamoufox:
    pid: int
    ws_url: str
    user_data_dir: Path
    exe_path: str
    proc: subprocess.Popen[bytes]


def _asset_for_arch() -> tuple[str, str]:
    machine = platform.machine()
    if machine not in CAMOUFOX_ASSETS:
        raise RuntimeError(f"no Camoufox build for arch {machine!r}; supported: {sorted(CAMOUFOX_ASSETS)}")
    return CAMOUFOX_ASSETS[machine]


def camoufox_home() -> Path:
    return CACHE_ROOT / CAMOUFOX_RELEASE_TAG


def camoufox_installed() -> bool:
    return (camoufox_home() / "camoufox").is_file()


def _verify_sha256(path: Path, expected: str) -> None:
    digest = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(DOWNLOAD_CHUNK), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise RuntimeError(f"Camoufox download sha256 mismatch: expected {expected}, got {actual}")


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "vesta-browser"})
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_S) as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f, DOWNLOAD_CHUNK)


def _extract_preserving_mode(zip_path: Path, dest: Path) -> None:
    """Extract, restoring unix exec bits (zipfile.extractall drops them, which would
    leave the camoufox binary and its .so loader non-executable)."""
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            z.extract(info, dest)
            mode = info.external_attr >> 16
            if mode:
                (dest / info.filename).chmod(mode)


def ensure_camoufox(override: str | None = None) -> str:
    """Return a path to the Camoufox executable, fetching + extracting on first use."""
    if override:
        if not Path(override).is_file():
            raise RuntimeError(f"executable not found: {override}")
        return override

    home = camoufox_home()
    exe = home / "camoufox"
    if exe.is_file():
        return str(exe)

    asset_name, expected_sha = _asset_for_arch()
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    tmp_zip = CACHE_ROOT / f".{asset_name}.part"
    _download(f"{RELEASE_DOWNLOAD_URL}/{CAMOUFOX_RELEASE_TAG}/{asset_name}", tmp_zip)
    _verify_sha256(tmp_zip, expected_sha)

    staging = CACHE_ROOT / f".{CAMOUFOX_RELEASE_TAG}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    _extract_preserving_mode(tmp_zip, staging)
    tmp_zip.unlink(missing_ok=True)

    # Atomic publish: rename staging -> home. If a concurrent launch already
    # published it, keep theirs and drop ours.
    if exe.is_file():
        shutil.rmtree(staging, ignore_errors=True)
    else:
        staging.replace(home)
    return str(exe)


def _read_ws_url(proc: subprocess.Popen[bytes], log_path: Path, timeout_s: float) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        text = log_path.read_text(errors="replace") if log_path.exists() else ""
        match = BIDI_RE.search(text)
        if match:
            # The bare ws://host:port serves Marionette's httpd and rejects the
            # upgrade with HTTP 200; the BiDi endpoint is at /session.
            return match.group(1).rstrip("/") + "/session"
        if proc.poll() is not None:
            raise RuntimeError(f"Camoufox exited (code {proc.returncode}) before BiDi was ready. Log tail:\n{text[-800:]}")
        time.sleep(READY_POLL_S)
    tail = log_path.read_text(errors="replace")[-800:] if log_path.exists() else "(no log)"
    raise RuntimeError(f"Camoufox did not announce BiDi within {timeout_s}s. Log tail:\n{tail}")


def _x_display_reachable(display: str) -> bool:
    """True iff an X server is actually accepting connections on `display`."""
    if shutil.which("xdpyinfo"):
        try:
            return (
                subprocess.run(
                    ["xdpyinfo", "-display", display],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                ).returncode
                == 0
            )
        except Exception:
            return False
    # Fallback when xdpyinfo isn't installed: probe the X11 unix socket directly.
    try:
        n = display.lstrip(":").split(".")[0]
        sock_path = f"/tmp/.X11-unix/X{n}"
        if not Path(sock_path).exists():
            return False
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(sock_path)
        s.close()
        return True
    except OSError:
        return False


def _ensure_xvfb(display: str, screen: str = "1920x1080x24") -> int | None:
    """Best-effort: guarantee an X server is up on `display` before a headed browser.

    Camoufox runs headless by default, so only the handover flow (streaming a headed
    browser to the user over VNC) needs this. Self-heals a dead/lock-stuck Xvfb in
    ~2s, serialised with an flock so concurrent launches don't stomp each other. Never
    raises; on failure the caller falls back to headless. `screen` is the Xvfb
    `WxHxDEPTH` geometry. Returns the pid of the server this call started so the caller
    can reap it, or None when one was already up (not ours to kill) or the launch failed.
    """
    if _x_display_reachable(display):
        return None
    xvfb = shutil.which("Xvfb")
    if not xvfb:
        return None
    n = display.lstrip(":").split(".")[0]
    lock_fd = None
    try:
        import fcntl

        lock_fd = os.open(f"/tmp/.vesta-xvfb-{n}.lock", os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        # Another launcher may have started it while we waited for the lock.
        if _x_display_reachable(display):
            return None
        # Safe to remove now: we just confirmed nothing is listening on :n.
        for stale in (f"/tmp/.X{n}-lock", f"/tmp/.X11-unix/X{n}"):
            with contextlib.suppress(OSError):
                Path(stale).unlink()
        proc = subprocess.Popen(
            [xvfb, display, "-screen", "0", screen, "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.time() + 5
        while time.time() < deadline:
            if _x_display_reachable(display):
                return proc.pid
            time.sleep(0.2)
        return proc.pid if _x_display_reachable(display) else None
    except Exception:
        return None
    finally:
        if lock_fd is not None:
            try:
                import fcntl

                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
            except OSError:
                pass


# Prefs for the headed path (handover): force software WebRender so Camoufox renders without a
# GPU. Camoufox ships no `glxtest` helper, so on a GL-less display (Xvfb) headed Gecko otherwise
# stalls during graphics init. swgl needs no GL and does not touch the fingerprint (WebGL still
# reports Camoufox's spoofed vendor/renderer, so we deliberately do NOT disable WebGL).
_HEADED_PREFS = 'user_pref("gfx.webrender.software", true);\nuser_pref("gfx.x11-glx.enabled", false);\n'


def _launch_env(profile_dir: Path, use_headless: bool, window_size: tuple[int, int] | None = None) -> dict[str, str]:
    """Build the child env: fingerprint config, plus headless/headed rendering hygiene."""
    env = {**os.environ, "HOME": str(Path.home())}
    preset = select_preset(profile_dir)
    if window_size:
        preset = fit_to_screen(preset, *window_size)
    env.update(camou_config_env(preset))
    if use_headless:
        env["MOZ_HEADLESS"] = "1"
        # Strip any inherited DISPLAY/WAYLAND_DISPLAY: headless Firefox still runs GTK init and
        # blocks trying to reach a dead display (e.g. a caller that set DISPLAY=:99 out of a
        # stock-Chromium habit, with no X server). Headless needs no display, so drop them.
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
    else:
        env["LIBGL_ALWAYS_SOFTWARE"] = "1"
    return env


def _ensure_headed_prefs(profile_dir: Path) -> None:
    """Write the software-render user.js so headed Camoufox starts on a GL-less display.

    handover.stop removes it again: the pref only matters for the headed handover, so it must
    not linger in the shared profile and follow later headless launches.
    """
    (profile_dir / "user.js").write_text(_HEADED_PREFS)


def launch(
    *,
    user_data_dir: Path | None = None,
    headless: bool = False,
    executable: str | None = None,
    extra_args: list[str] | None = None,
    log_path: Path | None = None,
    window_size: tuple[int, int] | None = None,
) -> RunningCamoufox:
    """Spawn Camoufox and wait for its BiDi WebSocket. Returns a RunningCamoufox handle.

    window_size refits the preset's spoofed screen/window geometry to a real screen so the
    window fills it exactly (Camoufox sizes the window to the spoofed window.outer*).
    """
    exe = ensure_camoufox(executable)
    profile_dir = user_data_dir or PROFILE_ROOT
    profile_dir.mkdir(parents=True, exist_ok=True)

    # Headless is the stealthy default: Camoufox's fingerprint is spoofed in C++, so
    # headless leaks nothing. Only run headed when a real display exists and headless
    # wasn't asked for (containers have no DISPLAY, so they always go headless).
    use_headless = headless or not os.environ.get("DISPLAY")

    args = [exe, "-no-remote", "-profile", str(profile_dir), "--remote-debugging-port", "0"]
    if use_headless:
        args.insert(1, "-headless")
    else:
        _ensure_headed_prefs(profile_dir)
    if extra_args:
        args += extra_args

    env = _launch_env(profile_dir, use_headless, window_size)

    stderr_log = log_path or Path(f"/tmp/vesta-camoufox-{os.getpid()}.log")
    # The child dups the fd; closing our copy after spawn lets this launch CLI exit
    # cleanly while the detached browser keeps writing.
    with stderr_log.open("w+b") as log_handle:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=log_handle,
            env=env,
            start_new_session=True,
        )

    try:
        ws_url = _read_ws_url(proc, stderr_log, READY_TIMEOUT_S)
    except Exception:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        raise

    return RunningCamoufox(
        pid=proc.pid,
        ws_url=ws_url,
        user_data_dir=profile_dir,
        exe_path=exe,
        proc=proc,
    )


def stop(running: RunningCamoufox, timeout_s: float = 5.0) -> None:
    proc = running.proc
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.1)
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
