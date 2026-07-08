"""Launch a stealth Chromium and wait until its CDP endpoint is reachable."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CDP_PORT_START = 9222
CDP_PORT_END = 9322
PROFILE_ROOT = Path.home() / ".browser" / "profile"
READY_TIMEOUT_S = 15.0
READY_POLL_S = 0.2

# Anti-detection Chrome args from Scrapling (https://github.com/D4Vinci/Scrapling).
# Applied when stealth is enabled to reduce automation fingerprint.
STEALTH_ARGS = [
    "--no-pings",
    "--disable-infobars",
    "--disable-breakpad",
    "--no-service-autorun",
    "--homepage=about:blank",
    "--disable-hang-monitor",
    "--disable-session-crashed-bubble",
    "--disable-search-engine-choice-screen",
    "--test-type",
    "--lang=en-US",
    "--mute-audio",
    "--hide-scrollbars",
    "--disable-logging",
    "--start-maximized",
    "--enable-async-dns",
    "--accept-lang=en-US",
    "--use-mock-keychain",
    "--disable-translate",
    "--disable-voice-input",
    "--window-position=0,0",
    "--disable-wake-on-wifi",
    "--ignore-gpu-blocklist",
    "--enable-tcp-fast-open",
    "--enable-web-bluetooth",
    "--disable-cloud-import",
    "--disable-print-preview",
    "--metrics-recording-only",
    "--disable-crash-reporter",
    "--disable-partial-raster",
    "--disable-gesture-typing",
    "--disable-checker-imaging",
    "--disable-prompt-on-repost",
    "--force-color-profile=srgb",
    "--font-render-hinting=none",
    "--aggressive-cache-discard",
    "--disable-domain-reliability",
    "--disable-threaded-animation",
    "--disable-threaded-scrolling",
    "--enable-simple-cache-backend",
    "--enable-surface-synchronization",
    "--disable-image-animation-resync",
    "--disable-renderer-backgrounding",
    "--disable-ipc-flooding-protection",
    "--prerender-from-omnibox=disabled",
    "--safebrowsing-disable-auto-update",
    "--disable-offer-upload-credit-cards",
    "--disable-background-timer-throttling",
    "--disable-new-content-rendering-timeout",
    "--run-all-compositor-stages-before-draw",
    "--disable-client-side-phishing-detection",
    "--disable-backgrounding-occluded-windows",
    "--disable-layer-tree-host-memory-pressure",
    "--autoplay-policy=user-gesture-required",
    "--disable-offer-store-unmasked-wallet-cards",
    "--disable-component-extensions-with-background-pages",
    "--enable-features=NetworkService,NetworkServiceInProcess,TrustTokens,TrustTokensAlwaysAllowIssuance,SharedArrayBuffer",
    "--blink-settings=primaryHoverType=2,availableHoverTypes=2,primaryPointerType=4,availablePointerTypes=4",
    "--disable-features=AudioServiceOutOfProcess,TranslateUI,BlinkGenPropertyTrees",
]

HARMFUL_ARGS = {
    "--enable-automation",
    "--disable-popup-blocking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-extensions",
}

LINUX_CHROMIUM_PATHS = [
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/snap/bin/chromium",
]

MAC_CHROMIUM_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]


@dataclass
class RunningChrome:
    pid: int
    cdp_port: int
    user_data_dir: Path
    exe_path: str
    proc: subprocess.Popen[bytes]


def find_chromium_executable(override: str | None = None) -> str:
    """Locate a chromium executable. Prefers playwright-core's installed chromium on Linux."""
    if override:
        if not Path(override).is_file():
            raise RuntimeError(f"executable not found: {override}")
        return override

    # Playwright-core installs chromium under ~/.cache/ms-playwright/chromium-*/chrome-linux/chrome.
    pw_cache = Path.home() / ".cache" / "ms-playwright"
    if pw_cache.is_dir():
        for d in sorted(pw_cache.glob("chromium-*"), reverse=True):
            for candidate in (
                d / "chrome-linux" / "chrome",
                d / "chrome-linux64" / "chrome",
                d / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
            ):
                if candidate.is_file():
                    return str(candidate)

    paths = LINUX_CHROMIUM_PATHS if sys.platform.startswith("linux") else MAC_CHROMIUM_PATHS
    for p in paths:
        if Path(p).is_file():
            return p

    which = shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("chrome")
    if which:
        return which

    raise RuntimeError("No chromium executable found. Install via `npx playwright-core install chromium` or set VESTA_BROWSER_EXECUTABLE.")


def _port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def find_free_port(start: int = CDP_PORT_START, end: int = CDP_PORT_END) -> int:
    for port in range(start, end):
        if _port_free(port):
            return port
    raise RuntimeError(f"No free CDP port in range {start}-{end}")


def is_cdp_reachable(port: int, timeout_s: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout_s) as r:
            return r.status == 200
    except (TimeoutError, OSError):
        # urllib raises URLError (OSError subclass) for refused/reset connections and
        # socket.timeout (TimeoutError) on the deadline. Treat both as "not ready yet".
        return False


def read_ws_url(port: int, timeout_s: float = 2.0) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout_s) as r:
        data = json.loads(r.read())
    if "webSocketDebuggerUrl" not in data or not data["webSocketDebuggerUrl"]:
        raise RuntimeError(f"/json/version on port {port} returned no webSocketDebuggerUrl")
    return data["webSocketDebuggerUrl"]


def _ensure_clean_exit(user_data_dir: Path) -> None:
    """Flip profile 'exited_cleanly' so Chrome doesn't show the crash bubble on next launch."""
    prefs_path = user_data_dir / "Default" / "Preferences"
    try:
        prefs = json.loads(prefs_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return
    prefs["exit_type"] = "Normal"
    prefs["exited_cleanly"] = True
    prefs_path.write_text(json.dumps(prefs))


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
                ).returncode
                == 0
            )
        except Exception:
            return False
    # Fallback when xdpyinfo isn't installed: probe the X11 unix socket directly.
    try:
        n = display.lstrip(":").split(".")[0]
        sock_path = f"/tmp/.X11-unix/X{n}"
        if not os.path.exists(sock_path):
            return False
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(sock_path)
        s.close()
        return True
    except OSError:
        return False


def _ensure_xvfb(display: str, screen: str = "1920x1080x24") -> bool:
    """Best-effort: guarantee an X server is up on `display` before headed Chrome.

    The Xvfb daemon is normally started at boot (restart skill), but if it died
    or never came up this self-heals in ~2s instead of letting Chrome fail with
    "Missing X server". Clears the stale lock an unclean shutdown leaves behind
    (which otherwise makes Xvfb refuse to start), serialised with an flock so
    concurrent launches don't stomp each other. Never raises; on failure the
    caller falls back to headless. `screen` is the Xvfb `WxHxDEPTH` geometry;
    handover uses a larger one so the streamed screen stays crisp on HiDPI.
    """
    if _x_display_reachable(display):
        return True
    xvfb = shutil.which("Xvfb")
    if not xvfb:
        return False
    n = display.lstrip(":").split(".")[0]
    lock_fd = None
    try:
        import fcntl

        lock_fd = os.open(f"/tmp/.vesta-xvfb-{n}.lock", os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        # Another launcher may have started it while we waited for the lock.
        if _x_display_reachable(display):
            return True
        # Safe to remove now: we just confirmed nothing is listening on :n.
        for stale in (f"/tmp/.X{n}-lock", f"/tmp/.X11-unix/X{n}"):
            try:
                os.remove(stale)
            except OSError:
                pass
        subprocess.Popen(
            [xvfb, display, "-screen", "0", screen, "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.time() + 5
        while time.time() < deadline:
            if _x_display_reachable(display):
                return True
            time.sleep(0.2)
        return _x_display_reachable(display)
    except Exception:
        return False
    finally:
        if lock_fd is not None:
            try:
                import fcntl

                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
            except OSError:
                pass


def launch(
    *,
    port: int | None = None,
    user_data_dir: Path | None = None,
    headless: bool = False,
    stealth: bool = False,
    no_sandbox: bool = False,
    executable: str | None = None,
    extra_args: list[str] | None = None,
    initial_url: str | None = None,
) -> RunningChrome:
    """Spawn a Chromium and wait for its CDP endpoint. Returns a RunningChrome handle."""
    exe = find_chromium_executable(executable)
    cdp_port = port or find_free_port()
    profile_dir = user_data_dir or PROFILE_ROOT
    profile_dir.mkdir(parents=True, exist_ok=True)
    _ensure_clean_exit(profile_dir)

    args = [
        exe,
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-features=Translate,MediaRouter",
        "--enable-features=SharedArrayBuffer",
        "--disable-blink-features=AutomationControlled",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--password-store=basic",
    ]

    # Stealth wants a real display (headless leaks a "HeadlessChrome" UA), so provision
    # one on demand instead of relying on a boot daemon: default to :99 when DISPLAY is
    # unset, then ensure an X server is actually up, self-healing a dead or lock-stuck
    # Xvfb. Zero setup, no restart-skill entry. If it can't come up, degrade to headless.
    display = os.environ.get("DISPLAY", "")
    if stealth and not display:
        display = ":99"
    has_display = bool(display)
    if stealth and display.startswith(":") and not _ensure_xvfb(display):
        has_display = False
        display = ""
    use_headless = headless and not (stealth and has_display)
    if use_headless:
        args += ["--headless=new", "--disable-gpu"]

    # Chromium refuses to run as root without --no-sandbox, and these containers
    # run as root, so auto-apply it when euid==0 (env/flag can still force it).
    running_as_root = sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0
    if no_sandbox or os.environ.get("VESTA_BROWSER_NO_SANDBOX") == "1" or running_as_root:
        args += ["--no-sandbox", "--disable-setuid-sandbox"]

    if sys.platform.startswith("linux"):
        args.append("--disable-dev-shm-usage")

    if stealth:
        existing_keys = {a.split("=", 1)[0] for a in args}
        args += [a for a in STEALTH_ARGS if a.split("=", 1)[0] not in existing_keys]
        args = [a for a in args if a not in HARMFUL_ARGS]

    if extra_args:
        args += extra_args

    args.append(initial_url or "about:blank")

    chrome_env = {**os.environ, "HOME": str(Path.home())}
    # Pass the (possibly defaulted) display through so Chrome uses it even when
    # DISPLAY wasn't set in the environment.
    if has_display and display:
        chrome_env["DISPLAY"] = display
    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=chrome_env,
    )

    deadline = time.time() + READY_TIMEOUT_S
    while time.time() < deadline:
        if is_cdp_reachable(cdp_port):
            return RunningChrome(
                pid=proc.pid,
                cdp_port=cdp_port,
                user_data_dir=profile_dir,
                exe_path=exe,
                proc=proc,
            )
        if proc.poll() is not None:
            break
        time.sleep(READY_POLL_S)

    # Stop the process first, then drain stderr so the failure message has
    # something useful in it. Reading from a PIPE before kill can hang if the
    # child is still blocked, and the original code closed stderr without
    # reading it, leaving every "Chromium did not become CDP-reachable" error
    # with stderr_tail=b''.
    try:
        proc.kill()
    except ProcessLookupError:
        pass

    stderr_bytes = b""
    if proc.stderr:
        try:
            stderr_bytes = proc.stderr.read() or b""
        except (OSError, ValueError):
            pass
        finally:
            try:
                proc.stderr.close()
            except OSError:
                pass

    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        pass

    raise RuntimeError(
        f"Chromium did not become CDP-reachable on port {cdp_port} within {READY_TIMEOUT_S}s. "
        f"exit_code={proc.returncode} stderr_tail={stderr_bytes[-500:]!r}"
    )


def stop(running: RunningChrome, timeout_s: float = 5.0) -> None:
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
    try:
        proc.kill()
    except ProcessLookupError:
        pass
