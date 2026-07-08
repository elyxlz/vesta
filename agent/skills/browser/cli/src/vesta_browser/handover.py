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
# A MacBook Retina native screen (2880x1800, 16:10) rendered at 2x device scale: Chrome lays
# out at 1440x900 CSS but paints 2x real pixels, so the streamed image is dense enough that
# noVNC downscaling it into the user's window stays crisp even on a HiDPI display. We do NOT
# ask the server to resize to the client (resizeSession): that would match CSS pixels and throw
# the Retina density away, which is what made the stream look soft.
SCREEN_W, SCREEN_H = 2880, 1800
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


# The live browser is framed as vesta's own laptop: a modern MacBook, seen head-on, with the
# stream as its screen. Silver aluminium in light, space-grey in dark (the machine is a physical
# object; the desk behind it takes the theme). The wordmark is etched on the base in the same
# system serif the vesta.run logotype uses; the status is a small light beside it. Personality
# comes from the object, so the screen itself stays clean and crisp (no CRT effects).
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
    --desk-1: oklch(0.95 0.008 80); --desk-2: oklch(0.89 0.012 75);
    --alu: oklch(0.83 0.003 250); --alu-hi: oklch(0.93 0.003 250); --alu-lo: oklch(0.71 0.005 250);
    --etch: oklch(0.46 0.004 250); --muted: oklch(0.553 0.015 80);
    --bezel: oklch(0.17 0 0); --screen-bg: oklch(0.97 0.006 80); --ok: oklch(0.66 0.17 150);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --desk-1: oklch(0.17 0.008 80); --desk-2: oklch(0.1 0.006 80);
      --alu: oklch(0.42 0.004 265); --alu-hi: oklch(0.52 0.004 265); --alu-lo: oklch(0.33 0.005 265);
      --etch: oklch(0.7 0.004 265); --muted: oklch(0.7 0.02 80);
      --bezel: oklch(0.12 0 0); --screen-bg: oklch(0.19 0.007 80); --ok: oklch(0.74 0.18 150);
    }
  }
  :root[data-theme="light"]{color-scheme:light;--desk-1:oklch(0.95 0.008 80);--desk-2:oklch(0.89 0.012 75);--alu:oklch(0.83 0.003 250);--alu-hi:oklch(0.93 0.003 250);--alu-lo:oklch(0.71 0.005 250);--etch:oklch(0.46 0.004 250);--muted:oklch(0.553 0.015 80);--bezel:oklch(0.17 0 0);--screen-bg:oklch(0.97 0.006 80);--ok:oklch(0.66 0.17 150);}
  :root[data-theme="dark"]{color-scheme:dark;--desk-1:oklch(0.17 0.008 80);--desk-2:oklch(0.1 0.006 80);--alu:oklch(0.42 0.004 265);--alu-hi:oklch(0.52 0.004 265);--alu-lo:oklch(0.33 0.005 265);--etch:oklch(0.7 0.004 265);--muted:oklch(0.7 0.02 80);--bezel:oklch(0.12 0 0);--screen-bg:oklch(0.19 0.007 80);--ok:oklch(0.74 0.18 150);}

  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: radial-gradient(130% 100% at 50% -20%, var(--desk-1), var(--desk-2));
    font-family: "Public Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    -webkit-font-smoothing: antialiased; overflow: hidden;
    display: grid; place-items: center; padding: 2.5vmin;
  }

  /* the machine: a lid (screen) + hinge + base, kept at a laptop aspect and centred */
  .macbook { width: min(96vw, calc(92vh * 1.51)); display: flex; flex-direction: column; align-items: center; }
  .lid {
    width: 100%; aspect-ratio: 16 / 10.6; border-radius: 20px; padding: 11px 11px 26px;
    background: linear-gradient(var(--alu-hi), var(--alu) 8%, var(--alu) 82%, var(--alu-lo));
    box-shadow: inset 0 1px 0 oklch(1 0 0 / 0.4), inset 0 0 0 1px oklch(0 0 0 / 0.12), 0 26px 60px -26px oklch(0 0 0 / 0.55);
    display: flex; flex-direction: column;
  }
  .bezel {
    position: relative; flex: 1 1 auto; min-height: 0; border-radius: 11px; background: var(--bezel);
    padding: 12px; box-shadow: inset 0 0 0 1px oklch(0 0 0 / 0.6);
    display: flex; flex-direction: column;
  }
  .notch { position: absolute; top: 0; left: 50%; transform: translateX(-50%); width: 15%; max-width: 150px; height: 8px; background: var(--bezel); border-radius: 0 0 6px 6px; z-index: 2; }
  #stage { position: relative; flex: 1 1 auto; min-height: 0; border-radius: 4px; overflow: hidden; background: var(--screen-bg); }
  #screen { width: 100%; height: 100%; }
  .glare { position: absolute; inset: 0; pointer-events: none; z-index: 3;
    background: linear-gradient(128deg, oklch(1 0 0 / 0.07) 0%, transparent 16%, transparent 100%); }
  /* etched brand on the aluminium below the screen */
  .badge { flex: 0 0 auto; height: 15px; margin-top: 8px; display: flex; align-items: center; justify-content: center; gap: 8px; }
  .wordmark { font-family: var(--serif); font-weight: 500; font-size: 13px; letter-spacing: -0.01em; color: var(--etch); text-shadow: 0 1px 0 oklch(1 0 0 / 0.35); }
  .wordmark .dim { opacity: 0.62; }
  .led { width: 6px; height: 6px; border-radius: 50%; background: var(--etch); opacity: .4; animation: pulse 1.6s infinite; }
  .badge.ok .led { background: var(--ok); opacity: 1; animation: none; box-shadow: 0 0 6px 1px color-mix(in oklch, var(--ok) 70%, transparent); }
  @keyframes pulse { 0%,100% { opacity: .25; } 50% { opacity: .7; } }

  /* hinge + the base front lip (with the opening notch), grounding it as a laptop */
  .hinge { width: 99%; height: 8px; background: linear-gradient(var(--alu-lo), var(--alu)); border-radius: 0 0 3px 3px; box-shadow: inset 0 1px 2px oklch(0 0 0 / 0.4); }
  .base { position: relative; width: 88%; height: 15px; background: linear-gradient(var(--alu), var(--alu-lo)); border-radius: 0 0 9px 9px;
    box-shadow: 0 12px 22px -10px oklch(0 0 0 / 0.55); }
  .base::before { content: ""; position: absolute; top: 0; left: 50%; transform: translateX(-50%); width: 13%; max-width: 120px; height: 5px; background: var(--alu-lo); border-radius: 0 0 5px 5px; box-shadow: inset 0 1px 2px oklch(0 0 0 / 0.35); }

  #overlay { position: absolute; inset: 0; display: grid; place-items: center; background: var(--screen-bg); transition: opacity .45s ease; z-index: 1; }
  #overlay.hidden { opacity: 0; pointer-events: none; }
  .spinner { width: 26px; height: 26px; border-radius: 50%; border: 2.5px solid oklch(0.5 0 0 / 0.2); border-top-color: var(--ok); animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  #overlay p { margin: 14px 0 0; color: var(--muted); font-size: 13px; }
  .overlay-inner { display: grid; justify-items: center; }
  @media (prefers-reduced-motion: reduce) { .led, .spinner, #overlay { animation: none !important; transition: none !important; } }
</style>
</head>
<body>
  <div class="macbook">
    <div class="lid">
      <div class="bezel">
        <div class="notch"></div>
        <div id="stage">
          <div id="screen"></div>
          <div id="overlay">
            <div class="overlay-inner">
              <div class="spinner"></div>
              <p>Waking vesta's computer</p>
            </div>
          </div>
          <div class="glare"></div>
        </div>
      </div>
      <div class="badge" id="badge">
        <span class="wordmark">vesta<span class="dim">'s browser</span></span>
        <span class="led"></span>
      </div>
    </div>
    <div class="hinge"></div>
    <div class="base"></div>
  </div>
  <script type="module">
    import RFB from './core/rfb.js';
    const overlay = document.getElementById('overlay');
    const badge = document.getElementById('badge');
    const base = location.pathname.replace(/[^/]*$/, '');
    const wsUrl = (location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + base + 'websockify';
    let rfb = null, attempts = 0;

    function connect() {
      badge.classList.remove('ok');
      rfb = new RFB(document.getElementById('screen'), wsUrl, { shared: true });
      // Downscale a dense fixed framebuffer (see SCREEN_W/H, rendered at 2x) into the window and
      // ask for near-lossless tiles so text stays crisp; the link is local/tunnelled so quality
      // is cheap. Do NOT resizeSession: that matches CSS pixels and discards the Retina density.
      rfb.scaleViewport = true;
      rfb.clipViewport = false;
      rfb.qualityLevel = 9;
      rfb.compressionLevel = 2;
      rfb.focusOnClick = true;
      rfb.addEventListener('connect', () => {
        attempts = 0;
        overlay.classList.add('hidden');
        badge.classList.add('ok');
        rfb.focus();
      });
      rfb.addEventListener('disconnect', () => {
        overlay.classList.remove('hidden');
        badge.classList.remove('ok');
        if (attempts++ < 30) setTimeout(connect, 1500);
      });
    }
    connect();
  </script>
</body>
</html>
"""
