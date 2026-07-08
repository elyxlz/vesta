"""Hand the live browser to the user over a clean web page so they can sign in.

Some sites (Microsoft/Google/banking) fingerprint automated browsers and block
device-code or scripted auth outright. The escape hatch is to let the *user* drive
the agent's real headed Chrome: sign in once by hand, then reuse the resulting
session cookies. This wraps the plumbing (headed Chrome under Xvfb -> x11vnc ->
websockify) but replaces noVNC's dated default UI with a branded auto-connecting
page, so what the user opens looks like Vesta, not a sketchy remote-desktop applet.

The public URL is the caller's job: register a `--public` vestad service to get a
port, pass it here as `--port`, and hand the user
`$VESTAD_TUNNEL/agents/$AGENT_NAME/<service>/handover.html`. vestad proxies the
websocket upgrade through that route, so the same page works for a remote user.
"""

from __future__ import annotations

import html
import os
import shutil
import socket
import subprocess
from pathlib import Path

from . import admin

HANDOVER_SESSION = "handover"
HANDOVER_PROFILE = Path.home() / ".browser" / "handover"
WEBROOT = Path.home() / ".cache" / "vesta-browser" / "handover-web"
VNC_PORT_START = 5900
WEB_PORT_START = 6080
DEFAULT_MESSAGE = "Sign in to continue. This is Vesta's browser, shown to you live."

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
    raise RuntimeError("noVNC not found (looked for core/rfb.js under /usr/share/novnc). Install it: apt-get install -y novnc x11vnc")


def _require_binaries() -> None:
    missing = [b for b in ("x11vnc", "websockify") if not shutil.which(b)]
    if missing:
        raise RuntimeError(f"missing {', '.join(missing)}. Install: apt-get install -y novnc x11vnc")


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


def render_page(message: str) -> str:
    return _PAGE_TEMPLATE.replace("__MESSAGE__", html.escape(message))


def _build_webroot(message: str) -> Path:
    """Assemble a web root: our branded page plus symlinks to noVNC's core + vendor."""
    novnc = _find_novnc_dir()
    if WEBROOT.exists():
        shutil.rmtree(WEBROOT)
    WEBROOT.mkdir(parents=True, exist_ok=True)
    (WEBROOT / "handover.html").write_text(render_page(message))
    for name in ("core", "vendor"):
        src = novnc / name
        if src.exists():
            (WEBROOT / name).symlink_to(src)
    return WEBROOT


def start(*, url: str | None, port: int | None, message: str | None, user_data_dir: str | None) -> dict[str, object]:
    """Bring up headed Chrome + x11vnc + websockify serving the branded page. Idempotent-ish: stops any prior handover first."""
    _require_binaries()
    stop()  # tear down a stale handover so ports and pids don't collide

    msg = message or DEFAULT_MESSAGE
    profile = Path(user_data_dir) if user_data_dir else HANDOVER_PROFILE

    # launch() provisions Xvfb on demand for a stealth headed browser; pin the display so
    # x11vnc mirrors the exact same screen Chrome renders on.
    display = os.environ.get("DISPLAY") or ":99"
    os.environ["DISPLAY"] = display
    running = admin.launch_chrome(
        HANDOVER_SESSION,
        headless=False,
        stealth=True,
        user_data_dir=profile,
        initial_url=url,
    )

    vnc_port = _free_port(VNC_PORT_START)
    web_port = port or _free_port(WEB_PORT_START)
    webroot = _build_webroot(msg)

    log = open(_session_file("handover-log"), "w")
    x11vnc = subprocess.Popen(
        ["x11vnc", "-display", display, "-localhost", "-rfbport", str(vnc_port), "-forever", "-shared", "-nopw", "-quiet", "-noxdamage"],
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
        "message": msg,
    }


def stop() -> dict[str, object]:
    """Tear down the handover: websockify, x11vnc, the headed Chrome, and the web root. Idempotent."""
    for suffix in ("websockify-pid", "x11vnc-pid"):
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
        "x11vnc": _alive(_read_pid("x11vnc-pid")),
        "websockify": _alive(_read_pid("websockify-pid")),
        "web_port": web_port,
        "page": "handover.html" if web_port else None,
    }


_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Vesta - sign in</title>
<style>
  :root { color-scheme: light dark; --bg:#f4f5f7; --card:#fff; --ink:#0e1116; --muted:#5b6472; --line:#e6e8ec; --accent:#4f46e5; --ok:#12a150; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0b0d10; --card:#14171c; --ink:#eef1f5; --muted:#98a2b3; --line:#232833; --accent:#8b8bff; --ok:#3ecf7a; }
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body { background: var(--bg); color: var(--ink); font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         display: flex; flex-direction: column; overflow: hidden; }
  header { flex: 0 0 auto; padding: 14px 18px; display: flex; align-items: center; gap: 12px;
           background: linear-gradient(180deg, var(--card), color-mix(in srgb, var(--card) 88%, var(--bg))); border-bottom: 1px solid var(--line); }
  .logo { width: 34px; height: 34px; border-radius: 9px; flex: 0 0 auto;
          background: linear-gradient(140deg, var(--accent), color-mix(in srgb, var(--accent) 55%, #ec4899));
          display: grid; place-items: center; box-shadow: 0 2px 10px color-mix(in srgb, var(--accent) 40%, transparent); }
  .logo svg { width: 19px; height: 19px; }
  .titles { min-width: 0; }
  .titles h1 { margin: 0; font-size: 15px; font-weight: 650; letter-spacing: -0.01em; }
  .titles p { margin: 1px 0 0; font-size: 12.5px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .pill { margin-left: auto; flex: 0 0 auto; display: inline-flex; align-items: center; gap: 7px;
          font-size: 12px; font-weight: 600; color: var(--muted); padding: 6px 11px; border: 1px solid var(--line);
          border-radius: 999px; background: var(--card); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: #d0a215; box-shadow: 0 0 0 0 color-mix(in srgb, #d0a215 60%, transparent); animation: pulse 1.6s infinite; }
  .pill.ok .dot { background: var(--ok); animation: none; box-shadow: none; }
  @keyframes pulse { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, #d0a215 55%, transparent); } 70% { box-shadow: 0 0 0 7px transparent; } 100% { box-shadow: 0 0 0 0 transparent; } }
  #stage { position: relative; flex: 1 1 auto; min-height: 0; background: #000; }
  #screen { width: 100%; height: 100%; }
  #overlay { position: absolute; inset: 0; display: grid; place-items: center; text-align: center;
             background: var(--bg); transition: opacity .35s ease; padding: 24px; }
  #overlay.hidden { opacity: 0; pointer-events: none; }
  .spinner { width: 30px; height: 30px; margin: 0 auto 16px; border-radius: 50%;
             border: 3px solid var(--line); border-top-color: var(--accent); animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  #overlay h2 { margin: 0 0 6px; font-size: 16px; font-weight: 650; }
  #overlay p { margin: 0; color: var(--muted); font-size: 13.5px; max-width: 340px; }
  footer { flex: 0 0 auto; padding: 9px 18px; font-size: 12px; color: var(--muted);
           border-top: 1px solid var(--line); background: var(--card); display: flex; align-items: center; gap: 8px; }
  footer svg { width: 14px; height: 14px; flex: 0 0 auto; color: var(--ok); }
</style>
</head>
<body>
  <header>
    <div class="logo"><svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M12 2 4 5v6c0 5 3.4 8.3 8 11 4.6-2.7 8-6 8-11V5l-8-3Z" fill="#fff" opacity=".95"/>
      <path d="M9 12l2.2 2.2L15.5 10" stroke="#4f46e5" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
    </svg></div>
    <div class="titles">
      <h1>Vesta</h1>
      <p>__MESSAGE__</p>
    </div>
    <span class="pill" id="pill"><span class="dot"></span><span id="pilltext">Connecting</span></span>
  </header>
  <div id="stage">
    <div id="screen"></div>
    <div id="overlay">
      <div>
        <div class="spinner"></div>
        <h2>Opening Vesta's browser</h2>
        <p>Hold on a moment. The live sign-in screen will appear here.</p>
      </div>
    </div>
  </div>
  <footer>
    <svg viewBox="0 0 24 24" fill="none"><path d="M12 2 4 5v6c0 5 3.4 8.3 8 11 4.6-2.7 8-6 8-11V5l-8-3Z" stroke="currentColor" stroke-width="1.6" fill="none"/></svg>
    <span>You are driving Vesta's own browser. Your password goes to the real sign-in page in the frame; Vesta keeps the session, not your password.</span>
  </footer>
  <script type="module">
    import RFB from './core/rfb.js';
    const overlay = document.getElementById('overlay');
    const pill = document.getElementById('pill');
    const pilltext = document.getElementById('pilltext');
    const base = location.pathname.replace(/[^/]*$/, '');
    const wsUrl = (location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + base + 'websockify';
    let rfb = null, attempts = 0;

    function setStatus(text, ok) {
      pilltext.textContent = text;
      pill.classList.toggle('ok', !!ok);
    }
    function connect() {
      setStatus(attempts ? 'Reconnecting' : 'Connecting', false);
      rfb = new RFB(document.getElementById('screen'), wsUrl, { shared: true });
      rfb.scaleViewport = true;
      rfb.clipViewport = false;
      rfb.focusOnClick = true;
      rfb.addEventListener('connect', () => {
        attempts = 0;
        overlay.classList.add('hidden');
        setStatus('Connected', true);
        rfb.focus();
      });
      rfb.addEventListener('disconnect', (e) => {
        setStatus('Reconnecting', false);
        overlay.classList.remove('hidden');
        if (attempts++ < 30) setTimeout(connect, 1500);
        else setStatus('Disconnected', false);
      });
    }
    connect();
  </script>
</body>
</html>
"""
