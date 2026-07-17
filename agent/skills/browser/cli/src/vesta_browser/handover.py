"""Hand the live browser to the user over a clean web page so they can sign in.

Some sites (Microsoft/Google/banking) fingerprint automated browsers and block
device-code or scripted auth outright. The escape hatch is to let the *user* drive
the agent's real headed Camoufox: sign in once by hand, then reuse the resulting
session cookies. This wraps the plumbing (headed Camoufox under Xvfb + a window
manager -> x11vnc -> websockify) but serves a branded page (Vesta's own type and
palette) instead of noVNC's dated default UI, so what the user opens reads as
Vesta, not a sketchy remote-desktop applet. It is deliberately generic: the page
says only "Vesta's browser"; the agent tells the user what to do in chat.

`start` makes the page reachable on its own: on a box it registers a public vestad
service and returns the ready-to-send `user_url`, so the agent needs no separate
register-service step and never hands the user a localhost link by mistake. Off a
box (dev/tests) it falls back to a local port.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

from . import admin, launcher

HANDOVER_SESSION = "handover"
WEBROOT = Path.home() / ".cache" / "vesta-browser" / "handover-web"
ASSETS_DIR = Path(__file__).parent / "assets" / "handover"
FONTS_DIR = ASSETS_DIR / "fonts"
VNC_PORT_START = 5900
WEB_PORT_START = 6080
# A 16:10 screen. Camoufox renders headed through software WebRender (it ships no GPU/glxtest
# helper), so a huge framebuffer would rasterize far too slowly on the CPU; 1600x1000 keeps the
# stream responsive, and 16:10 matches the MacBook frame in the page so the browser fills the
# screen cut-out.
SCREEN_W, SCREEN_H = 1600, 1000

# Public vestad service name for the handover page. The tunnel routes it at
# `$VESTAD_TUNNEL/agents/$AGENT_NAME/browser/handover.html` (no token).
HANDOVER_SERVICE = "browser"
REGISTER_SERVICE = Path.home() / "agent" / "skills" / "vestad" / "scripts" / "register-service"
SERVICE_REGISTER_TIMEOUT_S = 35  # register-service polls vestad up to ~30s before giving up

# The handover display shows exactly one app. Without this, openbox smart-places the window a
# few pixels off origin and adds a titlebar, so the stream sits misaligned in the page's screen
# cut-out. Strip decorations and pin every window maximized at the origin instead.
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


HANDOVER_BINARIES = ("x11vnc", "websockify", "openbox")


def readiness() -> dict[str, object]:
    """Report whether the handover prerequisites are installed, for `browser doctor` to surface the
    gap before the agent commits to escalating rather than at the moment it first tries to."""
    missing = [b for b in HANDOVER_BINARIES if not shutil.which(b)]
    try:
        _find_novnc_dir()
    except RuntimeError:
        missing.append("novnc")
    return {"ready": not missing, "missing": missing}


def _require_binaries() -> None:
    missing = [b for b in HANDOVER_BINARIES if not shutil.which(b)]
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


def _free_display(start: int = 99) -> str:
    """A display number with no live X server, so handover always provisions its OWN Xvfb.

    Reusing the ambient DISPLAY breaks on a real desktop seat: x11vnc cannot X_GetImage a live
    Wayland/Xorg screen (it fails BadMatch), so noVNC hangs on connect. Judge by liveness, not the
    socket FILE existing: a dead Xvfb leaves its /tmp/.X11-unix socket behind and nothing cleans it,
    so trusting file existence lets corpses exhaust the range. _ensure_xvfb clears a stale socket
    before launching on the number returned here."""
    for n in range(start, start + 100):
        if not launcher._x_display_reachable(f":{n}"):
            return f":{n}"
    raise RuntimeError(f"no free X display in range :{start}-:{start + 100}")


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


def _register_public_service() -> tuple[int, str] | None:
    """Register (idempotently) the public handover service and return (port, public_url).

    Returns None off a box, when there is no tunnel, agent name, or register-service script, so
    dev/tests fall back to a local port. This is what lets `handover start` hand the agent a
    ready-to-send URL instead of making it register a service and assemble the link by hand.
    """
    tunnel = os.environ["VESTAD_TUNNEL"] if "VESTAD_TUNNEL" in os.environ else ""
    agent = os.environ["AGENT_NAME"] if "AGENT_NAME" in os.environ else ""
    if not tunnel or not agent or not REGISTER_SERVICE.exists():
        return None
    result = subprocess.run(
        [str(REGISTER_SERVICE), HANDOVER_SERVICE, "--public"],
        capture_output=True,
        text=True,
        timeout=SERVICE_REGISTER_TIMEOUT_S,
        check=False,
    )
    if result.returncode != 0:
        return None
    port = int(result.stdout.strip())
    return port, f"{tunnel.rstrip('/')}/agents/{agent}/{HANDOVER_SERVICE}/handover.html"


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
    shutil.copyfile(ASSETS_DIR / "macbook.png", WEBROOT / "macbook.png")
    for name in ("core", "vendor"):
        src = novnc / name
        if src.exists():
            (WEBROOT / name).symlink_to(src)
    return WEBROOT


def start(*, url: str | None, port: int | None, user_data_dir: str | None) -> dict[str, object]:
    """Bring up headed Camoufox + a window manager + x11vnc + websockify serving the branded page.

    Idempotent-ish: stops any prior handover first so ports and pids don't collide. Returns a
    ready-to-send `user_url` (public tunnel link on a box, localhost off one).
    """
    _require_binaries()
    stop()

    # Resolve the port + the link to send the user. An explicit --port wins; otherwise, on a box,
    # register a public vestad service and use its port so the returned URL is the public tunnel
    # route; off a box, grab any local port.
    service = _register_public_service() if port is None else None
    if service is not None:
        web_port, user_url = service
    else:
        web_port = port or _free_port(WEB_PORT_START)
        user_url = f"http://localhost:{web_port}/handover.html"

    # Default to the shared browsing profile, not a throwaway one: whatever the user signs into
    # during the handover persists into the agent's everyday browser, so it grows more trusted
    # over time like a real user's. Camoufox (Firefox) single-instances a profile, so free the
    # lock by stopping the default session's browser and clearing its now-stale profile lock
    # before the headed handover takes the profile over.
    profile = Path(user_data_dir) if user_data_dir else launcher.PROFILE_ROOT
    admin.stop_browser("default")
    for lock in ("lock", ".parentlock"):
        (profile / lock).unlink(missing_ok=True)

    # Handover owns a dedicated Xvfb display, never the ambient one: x11vnc can grab a fresh Xvfb
    # but not a live desktop seat (a real :0 fails X_GetImage BadMatch, hanging noVNC), and a
    # desktop's DISPLAY=:0 would also render the headed browser onto the user's own monitor. On a
    # Wayland host x11vnc and Firefox both prefer the ambient Wayland session over our X11 display
    # (x11vnc 0.9.x exits outright when WAYLAND_DISPLAY is set), so drop it and force Firefox onto
    # X11 with MOZ_ENABLE_WAYLAND=0. Harmless where WAYLAND_DISPLAY is unset (e.g. the container).
    display = _free_display()
    os.environ["DISPLAY"] = display
    os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ["MOZ_ENABLE_WAYLAND"] = "0"

    # Bring the display up, then a window manager, then the headed browser. Two levers make the
    # window fill the cut-out for complementary reasons: openbox strips decorations and pins the
    # window at the origin (physical placement), while window_size refits the fingerprint's
    # screen/window geometry so what the page reports to JS matches the real 1600x1000 (fingerprint
    # coherence). The sign-in URL is passed as a trailing arg so it opens there.
    launcher._ensure_xvfb(display, screen=f"{SCREEN_W}x{SCREEN_H}x24")
    openbox_rc = _session_file("openbox-rc.xml")
    openbox_rc.write_text(OPENBOX_RC)
    openbox = subprocess.Popen(
        ["openbox", "--config-file", str(openbox_rc)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
    )
    running = admin.launch_browser(
        HANDOVER_SESSION,
        headless=False,
        user_data_dir=profile,
        extra_args=[url] if url else None,
        window_size=(SCREEN_W, SCREEN_H),
    )

    vnc_port = _free_port(VNC_PORT_START)
    webroot = _build_webroot()

    # -cursor most + -cursorpos send the real X cursor shape (hand over links, caret over text)
    # and its position, not a static dot. XDAMAGE (left on) means only changed regions are
    # re-encoded, so typing on the framebuffer stays responsive instead of repolling the whole
    # screen; -threads parallelises encoding for lower latency.
    with _session_file("handover-log").open("w") as log:
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
                "-threads",
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
    _session_file("profile").write_text(str(profile))

    return {
        "session": HANDOVER_SESSION,
        "user_url": user_url,
        "web_port": web_port,
        "vnc_port": vnc_port,
        "ws_url": running.ws_url,
        "display": display,
        "page": "handover.html",
        "profile": str(profile),
    }


def stop() -> dict[str, object]:
    """Tear down the handover: websockify, x11vnc, the WM, headed Camoufox, and the web root. Idempotent."""
    for suffix in ("websockify-pid", "x11vnc-pid", "openbox-pid"):
        pid = _read_pid(suffix)
        if pid is not None:
            admin._terminate_pid(pid)
        _session_file(suffix).unlink(missing_ok=True)
    admin.stop_browser(HANDOVER_SESSION)
    # The headed software-render prefs are handover-only; drop them from whichever profile this
    # handover used so later headless launches don't inherit them.
    profile_file = _session_file("profile")
    if profile_file.exists():
        (Path(profile_file.read_text().strip()) / "user.js").unlink(missing_ok=True)
    for suffix in ("web-port", "vnc-port", "handover-log", "openbox-rc.xml", "profile"):
        _session_file(suffix).unlink(missing_ok=True)
    if WEBROOT.exists():
        shutil.rmtree(WEBROOT)
    return {"stopped": True}


def status() -> dict[str, object]:
    web_port = _read_pid("web-port")
    return {
        "session": HANDOVER_SESSION,
        "browser": _alive(admin.read_session_browser_pid(HANDOVER_SESSION)),
        "openbox": _alive(_read_pid("openbox-pid")),
        "x11vnc": _alive(_read_pid("x11vnc-pid")),
        "websockify": _alive(_read_pid("websockify-pid")),
        "web_port": web_port,
        "page": "handover.html" if web_port else None,
    }


# The live browser is framed as vesta's own laptop. The frame is a real head-on MacBook photo
# (public-domain Pixabay render) with a transparent screen cut-out; the stream sits *behind* it
# and shows through the hole, so the aluminium and bezel are photographic, not hand-drawn. The
# screen rectangle was measured from the PNG (see the #stage offsets). The image is pointer-
# transparent so clicks and typing land on the browser underneath.
_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<!-- pinch-zoom left enabled (no maximum-scale, no scaling lock) so a phone user can zoom into a login field -->
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>vesta's browser</title>
<style>
  @font-face { font-family: "Public Sans"; src: url("./fonts/public-sans.woff2") format("woff2"); font-weight: 100 900; font-display: swap; }

  :root {
    color-scheme: light dark;
    --serif: ui-serif, Georgia, Cambria, "Times New Roman", Times, serif;
    --desk-1: oklch(0.95 0.008 80); --desk-2: oklch(0.88 0.014 75);
    --label: oklch(0.46 0.012 70); --screen-bg: oklch(0.97 0.006 80); --ok: oklch(0.66 0.17 150);
  }
  @media (prefers-color-scheme: dark) {
    :root { --desk-1: oklch(0.19 0.008 80); --desk-2: oklch(0.11 0.006 80); --label: oklch(0.72 0.02 80);
      --screen-bg: oklch(0.19 0.007 80); --ok: oklch(0.74 0.18 150); }
  }
  :root[data-theme="light"]{color-scheme:light;--desk-1:oklch(0.95 0.008 80);--desk-2:oklch(0.88 0.014 75);
    --label:oklch(0.46 0.012 70);--screen-bg:oklch(0.97 0.006 80);--ok:oklch(0.66 0.17 150);}
  :root[data-theme="dark"]{color-scheme:dark;--desk-1:oklch(0.19 0.008 80);--desk-2:oklch(0.11 0.006 80);
    --label:oklch(0.72 0.02 80);--screen-bg:oklch(0.19 0.007 80);--ok:oklch(0.74 0.18 150);}

  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: radial-gradient(135% 105% at 50% -25%, var(--desk-1), var(--desk-2));
    font-family: "Public Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; -webkit-font-smoothing: antialiased;
    overflow: hidden; display: flex; align-items: center; justify-content: center; padding: 1.2vmin;
  }
  /* the machine fills most of the viewport; container-type lets the chin engraving scale with it */
  .macbook { container-type: inline-size; position: relative; width: min(99vw, calc(97vh * 1.5725)); aspect-ratio: 1280 / 814; }
  /* the screen rectangle, measured from macbook.png: the live browser shows through the cut-out */
  #stage { position: absolute; left: 13.05%; top: 13.64%; width: 73.91%; height: 72.73%;
    overflow: hidden; background: var(--screen-bg); z-index: 0; }
  #screen { width: 100%; height: 100%; }
  .frame { position: absolute; inset: 0; width: 100%; height: 100%; z-index: 1;
    pointer-events: none; -webkit-user-drag: none; user-select: none; }
  #overlay { position: absolute; inset: 0; display: grid; place-items: center; background: var(--screen-bg); transition: opacity .45s ease; }
  #overlay.hidden { opacity: 0; pointer-events: none; }
  .spinner { width: 26px; height: 26px; border-radius: 50%; border: 2.5px solid oklch(0.5 0 0 / 0.2);
    border-top-color: var(--ok); animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  #overlay p { margin: 14px 0 0; color: var(--label); font-size: 13px; }
  .overlay-inner { display: grid; justify-items: center; }
  /* "vesta" engraved on the chin in place of the removed "MacBook Pro"; scales with the machine */
  .engraving { position: absolute; left: 0; right: 0; top: 88%; text-align: center; z-index: 2; pointer-events: none;
    font-family: var(--serif); font-weight: 500; font-size: 2.15cqw; letter-spacing: 0.02em;
    color: rgb(150, 150, 153); text-shadow: 0 1px 1px rgba(0, 0, 0, 0.55); }
  @media (prefers-reduced-motion: reduce) { .spinner, #overlay { animation: none !important; transition: none !important; } }

  /* Hidden textarea used only to summon the phone's soft keyboard: focusing it raises the
     on-screen keyboard, and its input events are forwarded to the remote session (see script).
     Kept in the DOM but off-screen and inert on desktop. */
  #kbdinput { position: fixed; left: 0; bottom: 0; width: 1px; height: 1px; padding: 0; margin: 0;
    border: 0; outline: 0; opacity: 0; background: transparent; color: transparent; resize: none;
    z-index: -1; pointer-events: none; }
  /* Floating "keyboard" affordance, shown only on touch/small screens (see media query below). */
  #kbd-button { position: fixed; right: max(14px, env(safe-area-inset-right)); bottom: max(14px, env(safe-area-inset-bottom));
    z-index: 10; display: none; align-items: center; gap: 6px; padding: 11px 15px; border: none; border-radius: 999px;
    font-family: inherit; font-size: 15px; font-weight: 600; color: #fff; background: var(--ok);
    box-shadow: 0 3px 12px rgba(0,0,0,0.32); cursor: pointer; -webkit-tap-highlight-color: transparent; touch-action: manipulation; }
  #kbd-button.active { background: var(--label); }
  #kbd-button .glyph { font-size: 18px; line-height: 1; }

  /* Phone / portrait / touch: drop the decorative MacBook photo frame entirely and let the live
     screen fill the viewport edge to edge, so login fields are tap-sized instead of a letterboxed
     strip inside a shrunken laptop. Desktop keeps the frame (this block does not apply there). */
  @media (max-width: 820px), (pointer: coarse) {
    body { padding: 0; }
    .macbook { width: 100vw; height: 100vh; height: 100dvh; aspect-ratio: auto; }
    .frame, .engraving { display: none; }
    #stage { left: 0; top: 0; width: 100%; height: 100%; }
    #kbd-button { display: flex; }
  }
</style>
</head>
<body>
  <div class="macbook">
    <div id="stage">
      <div id="screen"></div>
      <div id="overlay">
        <div class="overlay-inner">
          <div class="spinner"></div>
          <p>Waking vesta's computer</p>
        </div>
      </div>
    </div>
    <img class="frame" src="./macbook.png" alt="" draggable="false">
    <div class="engraving">vesta</div>
  </div>
  <textarea id="kbdinput" autocapitalize="off" autocomplete="off" autocorrect="off"
    spellcheck="false" aria-hidden="true" tabindex="-1"></textarea>
  <button id="kbd-button" type="button" aria-label="Show keyboard"><span class="glyph">⌨</span>Keyboard</button>
  <script type="module">
    import RFB from './core/rfb.js';
    import Keyboard from './core/input/keyboard.js';
    import KeyTable from './core/input/keysym.js';
    import keysyms from './core/input/keysymdef.js';
    const overlay = document.getElementById('overlay');
    const base = location.pathname.replace(/[^/]*$/, '');
    const wsUrl = (location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + base + 'websockify';
    let rfb = null, attempts = 0, lastText = '';

    function connect() {
      rfb = new RFB(document.getElementById('screen'), wsUrl, { shared: true });
      // Scale the fixed framebuffer (see SCREEN_W/H) to fit the cut-out and ask for near-lossless
      // tiles so text stays crisp; the link is local/tunnelled so quality is cheap. Do NOT
      // resizeSession: it would renegotiate the remote size to the CSS box and fight the fit.
      rfb.scaleViewport = true;
      rfb.clipViewport = false;
      rfb.qualityLevel = 9;
      rfb.compressionLevel = 2;
      rfb.focusOnClick = true;
      rfb.addEventListener('connect', () => {
        attempts = 0;
        overlay.classList.add('hidden');
        rfb.focus();
      });
      rfb.addEventListener('disconnect', () => {
        overlay.classList.remove('hidden');
        if (attempts++ < 30) setTimeout(connect, 1500);
      });
      // Remote copy -> local clipboard: mirror the remote selection out so a copy inside the
      // session lands in the user's own clipboard.
      rfb.addEventListener('clipboard', (e) => {
        if (e.detail && e.detail.text) {
          lastText = e.detail.text;
          if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(e.detail.text).catch(() => {});
        }
      });
    }

    // Local clipboard -> remote. The VNC canvas is not an editable element, so a normal 'paste'
    // event never fires; instead read the local clipboard on a user gesture and push it into the
    // remote selection. On any click the remote selection is kept current (so right-click Paste
    // works), and Cmd/Ctrl+V is intercepted to sync then inject a clean Ctrl+V, so it pastes
    // regardless of the local modifier (a Mac Cmd maps to Super on the Linux remote otherwise).
    async function readLocal() {
      if (!navigator.clipboard || !navigator.clipboard.readText) return '';
      try { return await navigator.clipboard.readText(); } catch (e) { return ''; }
    }
    async function syncToRemote() {
      const text = await readLocal();
      if (text && text !== lastText && rfb) { lastText = text; rfb.clipboardPasteFrom(text); }
    }
    document.addEventListener('pointerdown', syncToRemote);
    document.addEventListener('keydown', async (e) => {
      if (!((e.ctrlKey || e.metaKey) && (e.key === 'v' || e.key === 'V'))) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      const text = await readLocal();
      if (!rfb) return;
      if (text) { lastText = text; rfb.clipboardPasteFrom(text); }
      // release any modifier the real keypress left held on the remote, then a clean Ctrl+V
      rfb.sendKey(0xffeb, 'MetaLeft', false);
      rfb.sendKey(0xffe3, 'ControlLeft', false);
      rfb.sendKey(0xffe9, 'AltLeft', false);
      rfb.sendKey(0xffe3, 'ControlLeft', true);
      rfb.sendKey(0x0076, 'KeyV', true);
      rfb.sendKey(0x0076, 'KeyV', false);
      rfb.sendKey(0xffe3, 'ControlLeft', false);
    }, true);
    connect();

    // ── Mobile soft keyboard ──────────────────────────────────────────────────
    // The VNC canvas is not an editable element, so tapping it on a phone never raises the
    // on-screen keyboard and there is no way to type. Mirror noVNC's own proven technique: a
    // hidden <textarea> that we focus on demand to summon the soft keyboard. Two input paths run
    // in tandem so a normal login (email, password, 6-digit code, Enter/Backspace) works on both
    // platforms: a real noVNC Keyboard attached to the textarea catches Enter/Backspace and the
    // keydown-based keys iOS reports, while an input-diff fallback recovers the printable
    // characters Android IME keyboards insert without usable key codes. iOS keydowns call
    // preventDefault (so the textarea never changes and the diff path stays silent); Android IME
    // input ignores preventDefault (so only the diff path fires) — the two never double up.
    const isTouch = window.matchMedia('(pointer: coarse)').matches || 'ontouchstart' in window;
    if (isTouch) {
      const kbdInput = document.getElementById('kbdinput');
      const kbdButton = document.getElementById('kbd-button');
      const PAD = 100;              // padding so backspace always has text to delete against
      let last = '';
      function reset() { kbdInput.value = new Array(PAD).join('_'); last = kbdInput.value; }

      const touchKeyboard = new Keyboard(kbdInput);
      touchKeyboard.onkeyevent = (keysym, code, down) => { if (rfb) rfb.sendKey(keysym, code, down); };
      touchKeyboard.grab();

      // Android on-screen keyboards omit key codes; recover typed/deleted characters by diffing
      // the textarea value against its previous state (verbatim from noVNC's keyInput handler).
      kbdInput.addEventListener('input', (event) => {
        if (!rfb) return;
        const newValue = event.target.value;
        if (!last) reset();
        const oldValue = last;
        let newLen;
        try { newLen = Math.max(event.target.selectionStart, newValue.length); }
        catch (err) { newLen = newValue.length; }
        const oldLen = oldValue.length;
        let inputs = newLen - oldLen;
        let backspaces = inputs < 0 ? -inputs : 0;
        for (let i = 0; i < Math.min(oldLen, newLen); i++) {
          if (newValue.charAt(i) != oldValue.charAt(i)) { inputs = newLen - i; backspaces = oldLen - i; break; }
        }
        for (let i = 0; i < backspaces; i++) rfb.sendKey(KeyTable.XK_BackSpace, 'Backspace');
        for (let i = newLen - inputs; i < newLen; i++) rfb.sendKey(keysyms.lookup(newValue.charCodeAt(i)));
        if (newLen > 2 * PAD) { reset(); }
        else if (newLen < 1) { reset(); event.target.blur(); setTimeout(() => event.target.focus(), 0); }
        else { last = newValue; }
      });

      // While the soft keyboard is up, stop RFB from stealing focus back to the canvas on each tap
      // (focusOnClick=false) so tapping between login fields keeps the keyboard open; the tap still
      // clicks the remote field, it just doesn't move browser focus off the textarea.
      function showKeyboard() {
        reset();
        kbdInput.style.pointerEvents = 'auto';
        kbdInput.focus();
        try { const l = kbdInput.value.length; kbdInput.setSelectionRange(l, l); } catch (e) {}
        if (rfb) rfb.focusOnClick = false;
        kbdButton.classList.add('active');
      }
      function hideKeyboard() {
        kbdInput.blur();
        kbdInput.style.pointerEvents = 'none';
        if (rfb) rfb.focusOnClick = true;
        kbdButton.classList.remove('active');
      }
      kbdInput.addEventListener('blur', () => {
        kbdInput.style.pointerEvents = 'none';
        if (rfb) rfb.focusOnClick = true;
        kbdButton.classList.remove('active');
      });
      kbdButton.addEventListener('click', (e) => {
        e.preventDefault();
        if (kbdButton.classList.contains('active')) hideKeyboard(); else showKeyboard();
      });
    }
  </script>
</body>
</html>
"""
