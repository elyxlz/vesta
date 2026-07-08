"""Hand the live browser to the user over a clean web page so they can sign in.

Some sites (Microsoft/Google/banking) fingerprint automated browsers and block
device-code or scripted auth outright. The escape hatch is to let the *user* drive
the agent's real headed Chrome: sign in once by hand, then reuse the resulting
session cookies. This wraps the plumbing (headed Chrome under Xvfb + a window
manager -> x11vnc -> websockify) but serves a branded page (Vesta's own type and
palette) instead of noVNC's dated default UI, so what the user opens reads as
Vesta, not a sketchy remote-desktop applet. It is deliberately generic: the page
says only "Vesta's browser"; the agent tells the user what to do in chat.

The public URL is the caller's job: register a `--public` vestad service to get a
port, pass it here as `--port`, and hand the user
`$VESTAD_TUNNEL/agents/$AGENT_NAME/<service>/handover.html`. vestad proxies the
websocket upgrade through that route, so the same page works for a remote user.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

from . import admin, launcher

HANDOVER_SESSION = "handover"
HANDOVER_PROFILE = Path.home() / ".browser" / "handover"
WEBROOT = Path.home() / ".cache" / "vesta-browser" / "handover-web"
FONTS_DIR = Path(__file__).parent / "assets" / "handover" / "fonts"
VNC_PORT_START = 5900
WEB_PORT_START = 6080
# A high-resolution virtual screen rendered at 2x device scale (like a Retina panel): Chrome
# lays out at 1280x720 CSS but paints 2560x1440 real pixels, so the streamed image stays crisp
# when noVNC scales it into the user's window.
SCREEN_W, SCREEN_H = 2560, 1440
DEVICE_SCALE = 2

# Debian's `novnc` package installs here; a few distros relocate it.
NOVNC_DIRS = [
    Path("/usr/share/novnc"),
    Path("/usr/share/webapps/novnc"),
    Path("/usr/lib/novnc"),
]


def _session_file(suffix: str) -> Path:
    return Path(f"/tmp/vesta-browser-{HANDOVER_SESSION}.{suffix}")


def _find_novnc_dir() -> Path:
    for d in NOVNC_DIRS:
        if (d / "core" / "rfb.js").is_file():
            return d
    raise RuntimeError("noVNC not found (looked for core/rfb.js under /usr/share/novnc). Install it: apt-get install -y novnc x11vnc openbox")


def _require_binaries() -> None:
    missing = [b for b in ("x11vnc", "websockify", "openbox") if not shutil.which(b)]
    if missing:
        raise RuntimeError(f"missing {', '.join(missing)}. Install: apt-get install -y novnc x11vnc openbox")


def _free_port(start: int) -> int:
    for port in range(start, start + 200):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
        finally:
            s.close()
    raise RuntimeError(f"no free port in range {start}-{start + 200}")


def _alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_pid(suffix: str) -> int | None:
    try:
        return int(_session_file(suffix).read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def render_page() -> str:
    return _PAGE_TEMPLATE


def _build_webroot() -> Path:
    """Assemble a web root: the branded page, the bundled fonts, and symlinks to noVNC's core + vendor."""
    novnc = _find_novnc_dir()
    if WEBROOT.exists():
        shutil.rmtree(WEBROOT)
    WEBROOT.mkdir(parents=True, exist_ok=True)
    (WEBROOT / "handover.html").write_text(render_page())
    (WEBROOT / "fonts").mkdir()
    shutil.copyfile(FONTS_DIR / "public-sans.woff2", WEBROOT / "fonts" / "public-sans.woff2")
    for name in ("core", "vendor"):
        src = novnc / name
        if src.exists():
            (WEBROOT / name).symlink_to(src)
    return WEBROOT


def start(*, url: str | None, port: int | None, user_data_dir: str | None) -> dict[str, object]:
    """Bring up headed Chrome + a window manager + x11vnc + websockify serving the branded page.

    Idempotent-ish: stops any prior handover first so ports and pids don't collide.
    """
    _require_binaries()
    stop()

    profile = Path(user_data_dir) if user_data_dir else HANDOVER_PROFILE

    # launch() provisions Xvfb on demand for a stealth headed browser; pin the display so
    # x11vnc mirrors the exact same screen Chrome renders on. On a Wayland host, x11vnc and
    # Chrome both prefer the ambient Wayland session over our Xvfb X11 display (x11vnc 0.9.x
    # exits outright when WAYLAND_DISPLAY is set), so drop it: handover owns a dedicated X11
    # display. Harmless where WAYLAND_DISPLAY is unset (e.g. the container).
    display = os.environ.get("DISPLAY") or ":99"
    os.environ["DISPLAY"] = display
    os.environ.pop("WAYLAND_DISPLAY", None)

    # Bring the display up, then a window manager, then the headed browser. Three flags make a
    # headed Chrome usable through x11vnc on Xvfb: --ozone-platform=x11 forces the X11 backend
    # (on a Wayland host Chrome's Ozone otherwise auto-selects Wayland from XDG_SESSION_TYPE and
    # never paints the X screen x11vnc mirrors, so the stream is black); --window-size fills the
    # Xvfb screen; --disable-gpu keeps it on the software path Xvfb provides.
    launcher._ensure_xvfb(display, screen=f"{SCREEN_W}x{SCREEN_H}x24")
    openbox = subprocess.Popen(["openbox"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    running = admin.launch_chrome(
        HANDOVER_SESSION,
        headless=False,
        stealth=True,
        user_data_dir=profile,
        extra_args=[
            f"--window-size={SCREEN_W},{SCREEN_H}",
            f"--force-device-scale-factor={DEVICE_SCALE}",
            "--disable-gpu",
            "--ozone-platform=x11",
        ],
        initial_url=url,
    )

    vnc_port = _free_port(VNC_PORT_START)
    web_port = port or _free_port(WEB_PORT_START)
    webroot = _build_webroot()

    log = open(_session_file("handover-log"), "w")
    # -cursor most + -cursorpos send the real X cursor shape (so it turns into a hand over
    # links, a caret over text) and its position, instead of a static dot. -noxdamage keeps the
    # mirror reliable on Xvfb; the client asks for high quality (see the page's qualityLevel).
    x11vnc = subprocess.Popen(
        [
            "x11vnc",
            "-display",
            display,
            "-localhost",
            "-rfbport",
            str(vnc_port),
            "-forever",
            "-shared",
            "-nopw",
            "-quiet",
            "-noxdamage",
            "-cursor",
            "most",
            "-cursorpos",
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    websockify = subprocess.Popen(
        ["websockify", "--web", str(webroot), str(web_port), f"localhost:{vnc_port}"],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    _session_file("openbox-pid").write_text(str(openbox.pid))
    _session_file("x11vnc-pid").write_text(str(x11vnc.pid))
    _session_file("websockify-pid").write_text(str(websockify.pid))
    _session_file("web-port").write_text(str(web_port))
    _session_file("vnc-port").write_text(str(vnc_port))

    return {
        "session": HANDOVER_SESSION,
        "web_port": web_port,
        "vnc_port": vnc_port,
        "cdp_port": running.cdp_port,
        "display": display,
        "page": "handover.html",
        "profile": str(profile),
    }


def stop() -> dict[str, object]:
    """Tear down the handover: websockify, x11vnc, the WM, the headed Chrome, and the web root. Idempotent."""
    for suffix in ("websockify-pid", "x11vnc-pid", "openbox-pid"):
        pid = _read_pid(suffix)
        if pid is not None:
            admin._terminate_pid(pid)
        _session_file(suffix).unlink(missing_ok=True)
    admin.stop_chrome(HANDOVER_SESSION)
    for suffix in ("web-port", "vnc-port", "handover-log"):
        _session_file(suffix).unlink(missing_ok=True)
    if WEBROOT.exists():
        shutil.rmtree(WEBROOT)
    return {"stopped": True}


def status() -> dict[str, object]:
    web_port = _read_pid("web-port")
    return {
        "session": HANDOVER_SESSION,
        "chrome": _alive(admin.read_session_chrome_pid(HANDOVER_SESSION)),
        "openbox": _alive(_read_pid("openbox-pid")),
        "x11vnc": _alive(_read_pid("x11vnc-pid")),
        "websockify": _alive(_read_pid("websockify-pid")),
        "web_port": web_port,
        "page": "handover.html" if web_port else None,
    }


# Palette + type lifted from the vesta-cloud landing page: warm neutrals (oklch hue 80), a
# champagne primary, the same system serif the vesta.run logotype uses for the "vesta"
# wordmark, and Public Sans for the small text. The trust signal here is the look, not a
# paragraph of reassurance, so the chrome stays spare.
_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>vesta's browser</title>
<style>
  @font-face { font-family: "Public Sans"; src: url("./fonts/public-sans.woff2") format("woff2"); font-weight: 100 900; font-display: swap; }

  :root {
    color-scheme: light dark;
    --serif: ui-serif, Georgia, Cambria, "Times New Roman", Times, serif;
    --bg: oklch(0.995 0.005 80);
    --card: oklch(0.995 0.005 80);
    --fg: oklch(0.147 0.005 80);
    --muted: oklch(0.553 0.015 80);
    --line: oklch(0.147 0.005 80 / 0.10);
    --primary: oklch(0.8186 0.0795 66.78);
    --ok: oklch(0.68 0.17 150);
    --frame: oklch(0.97 0.006 80);
    --edge: oklch(1 0 0 / 0.6);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: oklch(0.147 0.005 80);
      --card: oklch(0.216 0.007 80);
      --fg: oklch(0.985 0.006 80);
      --muted: oklch(0.709 0.02 80);
      --line: oklch(1 0 0 / 0.08);
      --ok: oklch(0.78 0.19 150);
      --frame: oklch(0.19 0.007 80);
      --edge: oklch(1 0 0 / 0.06);
    }
  }
  :root[data-theme="light"] {
    color-scheme: light;
    --bg: oklch(0.995 0.005 80); --card: oklch(0.995 0.005 80); --fg: oklch(0.147 0.005 80);
    --muted: oklch(0.553 0.015 80); --line: oklch(0.147 0.005 80 / 0.10); --ok: oklch(0.68 0.17 150); --frame: oklch(0.97 0.006 80); --edge: oklch(1 0 0 / 0.6);
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --bg: oklch(0.147 0.005 80); --card: oklch(0.216 0.007 80); --fg: oklch(0.985 0.006 80);
    --muted: oklch(0.709 0.02 80); --line: oklch(1 0 0 / 0.08); --ok: oklch(0.78 0.19 150); --frame: oklch(0.19 0.007 80); --edge: oklch(1 0 0 / 0.06);
  }

  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg); color: var(--fg);
    font-family: "Public Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
    display: flex; flex-direction: column; overflow: hidden;
  }
  header {
    flex: 0 0 auto; padding: 15px 22px; display: flex; align-items: center; gap: 12px;
    background: var(--card); border-bottom: 1px solid var(--line); box-shadow: 0 1px 0 var(--edge) inset;
  }
  .wordmark {
    font-family: var(--serif); font-weight: 500; font-size: 20px; letter-spacing: -0.02em; color: var(--fg);
  }
  .wordmark .dim { color: var(--muted); }
  .pill {
    margin-left: auto; display: inline-flex; align-items: center; gap: 7px;
    font-size: 12px; font-weight: 500; color: var(--muted); letter-spacing: 0.01em;
  }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); opacity: .6; animation: pulse 1.6s infinite; }
  .pill.ok { color: var(--fg); }
  .pill.ok .dot { background: var(--ok); opacity: 1; animation: none; box-shadow: 0 0 0 3px color-mix(in oklch, var(--ok) 20%, transparent); }
  @keyframes pulse { 0%,100% { opacity: .3; } 50% { opacity: .9; } }

  #stage { position: relative; flex: 1 1 auto; min-height: 0; background: var(--frame); }
  #screen { width: 100%; height: 100%; }

  #overlay {
    position: absolute; inset: 0; display: grid; place-items: center;
    background: var(--frame); transition: opacity .45s ease;
  }
  #overlay.hidden { opacity: 0; pointer-events: none; }
  .spinner {
    width: 26px; height: 26px; border-radius: 50%;
    border: 2.5px solid var(--line); border-top-color: var(--primary); animation: spin .8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  #overlay p { margin: 14px 0 0; color: var(--muted); font-size: 13px; letter-spacing: 0.01em; }
  .overlay-inner { display: grid; justify-items: center; }

  @media (prefers-reduced-motion: reduce) { .dot, .spinner, #overlay { animation: none !important; transition: none !important; } }
</style>
</head>
<body>
  <header>
    <span class="wordmark">vesta<span class="dim">'s browser</span></span>
    <span class="pill" id="pill"><span class="dot"></span><span id="pilltext">Connecting</span></span>
  </header>
  <div id="stage">
    <div id="screen"></div>
    <div id="overlay">
      <div class="overlay-inner">
        <div class="spinner"></div>
        <p>Connecting to Vesta's browser</p>
      </div>
    </div>
  </div>
  <script type="module">
    import RFB from './core/rfb.js';
    const overlay = document.getElementById('overlay');
    const pill = document.getElementById('pill');
    const pilltext = document.getElementById('pilltext');
    const base = location.pathname.replace(/[^/]*$/, '');
    const wsUrl = (location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + base + 'websockify';
    let rfb = null, attempts = 0;

    function connect() {
      pilltext.textContent = attempts ? 'Reconnecting' : 'Connecting';
      pill.classList.remove('ok');
      rfb = new RFB(document.getElementById('screen'), wsUrl, { shared: true });
      // Ask the server to match its framebuffer to this window (1:1, no scaling blur) and to
      // send near-lossless tiles so text stays crisp; the link is local/tunnelled so bandwidth
      // is cheap. scaleViewport is the fallback if the server refuses to resize.
      rfb.resizeSession = true;
      rfb.scaleViewport = true;
      rfb.clipViewport = false;
      rfb.qualityLevel = 9;
      rfb.compressionLevel = 2;
      rfb.focusOnClick = true;
      rfb.addEventListener('connect', () => {
        attempts = 0;
        overlay.classList.add('hidden');
        pill.classList.add('ok');
        pilltext.textContent = 'Connected';
        rfb.focus();
      });
      rfb.addEventListener('disconnect', () => {
        overlay.classList.remove('hidden');
        pill.classList.remove('ok');
        if (attempts++ < 30) setTimeout(connect, 1500);
        else pilltext.textContent = 'Disconnected';
      });
    }
    connect();
  </script>
</body>
</html>
"""
