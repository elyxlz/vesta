"""Handover tests: page rendering, web-root assembly, dependency checks, teardown.

Hermetic: no real x11vnc/websockify/Chrome. The transport (VNC over the vestad
websocket proxy) is exercised end-to-end in a real container, not here.
"""

from __future__ import annotations

import socket

import pytest
from vesta_browser import handover


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Point the module's writable paths at tmp and give each test its own session name."""
    monkeypatch.setattr(handover, "WEBROOT", tmp_path / "web")
    monkeypatch.setattr(handover, "HANDOVER_SESSION", "test-" + tmp_path.name)
    return tmp_path


def _fake_novnc(root):
    novnc = root / "novnc"
    (novnc / "core").mkdir(parents=True)
    (novnc / "core" / "rfb.js").write_text("export default class RFB {}")
    (novnc / "vendor").mkdir()
    (novnc / "vendor" / "pako").mkdir()
    return novnc


# ── page rendering ────────────────────────────────────────────


def test_page_is_generic_not_task_specific():
    # The page names only "vesta's browser"; the agent conveys the actual task in chat.
    page = handover.render_page()
    assert "vesta" in page and "browser" in page
    assert "Outlook" not in page


def test_page_uses_vesta_cloud_fonts():
    page = handover.render_page()
    assert "./fonts/public-sans.woff2" in page  # bundled body font
    assert "--serif:" in page  # wordmark uses the vesta.run logotype serif stack


def test_page_connects_to_relative_websockify_path():
    # The WS URL is derived from the page's own path so it works behind the
    # vestad service proxy at /agents/<name>/<service>/handover.html.
    page = handover.render_page()
    assert "import RFB from './core/rfb.js'" in page
    assert "base + 'websockify'" in page


def test_page_is_mobile_usable():
    # On a phone the decorative MacBook frame is dropped and the live screen fills the viewport,
    # and a soft-keyboard affordance is present so the user can type email/password/MFA. Guard the
    # pieces that make touch sign-in work; desktop still keeps the frame.
    page = handover.render_page()
    assert "@media (max-width: 820px), (pointer: coarse)" in page  # responsive breakpoint
    assert ".frame, .engraving { display: none; }" in page  # frame dropped on mobile
    assert 'id="kbd-button"' in page and 'id="kbdinput"' in page  # keyboard button + hidden input
    assert "import Keyboard from './core/input/keyboard.js'" in page  # noVNC keyboard wiring
    assert "keysyms.lookup" in page  # Android input-diff -> keysym fallback
    assert "user-scalable=no" not in page  # pinch-zoom must stay enabled on touch


# ── web-root assembly ─────────────────────────────────────────


def test_build_webroot_writes_page_fonts_and_symlinks_novnc(isolated, monkeypatch):
    novnc = _fake_novnc(isolated)
    monkeypatch.setattr(handover, "NOVNC_DIRS", [novnc])
    root = handover._build_webroot()
    assert (root / "handover.html").is_file()
    assert (root / "fonts" / "public-sans.woff2").is_file()
    assert (root / "core" / "rfb.js").is_file()  # resolves through the symlink
    assert (root / "vendor" / "pako").is_dir()


def test_build_webroot_is_rebuildable(isolated, monkeypatch):
    novnc = _fake_novnc(isolated)
    monkeypatch.setattr(handover, "NOVNC_DIRS", [novnc])
    handover._build_webroot()
    root = handover._build_webroot()  # a second build wipes and recreates cleanly
    assert (root / "handover.html").is_file()


def test_bundled_font_exists_in_the_package():
    assert (handover.FONTS_DIR / "public-sans.woff2").is_file()


def test_find_novnc_dir_raises_with_install_hint(monkeypatch, tmp_path):
    monkeypatch.setattr(handover, "NOVNC_DIRS", [tmp_path / "absent"])
    with pytest.raises(RuntimeError, match="apt-get install"):
        handover._find_novnc_dir()


# ── dependency checks ─────────────────────────────────────────


def test_require_binaries_lists_missing(monkeypatch):
    monkeypatch.setattr(handover.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="Xvfb, x11vnc, websockify, openbox"):
        handover._require_binaries()


def test_missing_xvfb_alone_is_refused_not_hung(monkeypatch, isolated):
    # _ensure_xvfb never raises, so an unguarded Xvfb leaves x11vnc with no display to open and
    # the page spinning on "Waking" forever. The gate has to catch it up front.
    monkeypatch.setattr(handover, "NOVNC_DIRS", [_fake_novnc(isolated)])
    monkeypatch.setattr(handover.shutil, "which", lambda name: None if name == "Xvfb" else f"/usr/bin/{name}")
    with pytest.raises(RuntimeError, match="missing Xvfb"):
        handover._require_binaries()
    assert handover.readiness() == {"ready": False, "missing": ["Xvfb"]}


def test_install_hint_covers_every_required_binary(monkeypatch):
    # The hint is what an agent actually runs, so a package short of the gate strands it in a
    # state doctor calls ready. xvfb ships Xvfb, novnc ships websockify.
    monkeypatch.setattr(handover.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError) as excinfo:
        handover._require_binaries()
    hint = str(excinfo.value)
    assert handover.HANDOVER_APT_LINE in hint
    for package in ("xvfb", "novnc", "x11vnc", "openbox"):
        assert package in handover.HANDOVER_APT_LINE


def test_require_binaries_ok_when_present(monkeypatch):
    monkeypatch.setattr(handover.shutil, "which", lambda name: f"/usr/bin/{name}")
    handover._require_binaries()  # does not raise


# ── teardown ──────────────────────────────────────────────────


def _record_kills(monkeypatch):
    killed: list[int] = []
    monkeypatch.setattr(handover.admin, "_terminate_pid", killed.append)
    monkeypatch.setattr(handover.admin, "stop_browser", lambda _name: None)
    return killed


def test_stop_reaps_the_xvfb_it_started(monkeypatch):
    # Nothing else reaps Xvfb, and a live leftover keeps answering on its display number, so
    # _free_display climbs to the next one and the range runs dry after enough handovers.
    killed = _record_kills(monkeypatch)
    for suffix, pid in (("websockify-pid", 11), ("x11vnc-pid", 22), ("openbox-pid", 33), ("xvfb-pid", 44)):
        handover._session_file(suffix).write_text(str(pid))
    handover.stop()
    assert killed == [11, 22, 33, 44]  # Xvfb last: the bridge and browser are its clients
    assert not handover._session_file("xvfb-pid").exists()


def test_stop_is_idempotent_without_an_xvfb_pid(monkeypatch):
    killed = _record_kills(monkeypatch)
    assert handover.stop() == {"stopped": True}
    assert killed == []


def test_readiness_reports_missing_binaries(monkeypatch):
    monkeypatch.setattr(handover.shutil, "which", lambda _: None)
    report = handover.readiness()
    assert report["ready"] is False
    assert set(handover.HANDOVER_BINARIES) <= set(report["missing"])


def test_readiness_ok_when_all_present(monkeypatch, isolated):
    monkeypatch.setattr(handover.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(handover, "NOVNC_DIRS", [_fake_novnc(isolated)])
    assert handover.readiness() == {"ready": True, "missing": []}


# ── public service registration ───────────────────────────────


def test_register_public_service_none_off_box(monkeypatch):
    # No tunnel / agent env means dev or tests: fall back to a local port, no registration.
    monkeypatch.delenv("VESTAD_TUNNEL", raising=False)
    monkeypatch.delenv("AGENT_NAME", raising=False)
    assert handover._register_public_service() is None


def test_register_public_service_returns_port_and_public_url(monkeypatch, tmp_path):
    monkeypatch.setenv("VESTAD_TUNNEL", "https://box.vesta.run/")
    monkeypatch.setenv("AGENT_NAME", "ada")
    script = tmp_path / "register-service"
    script.write_text("#!/bin/sh\necho 7431\n")
    script.chmod(0o755)
    monkeypatch.setattr(handover, "REGISTER_SERVICE", script)
    port, url = handover._register_public_service()
    assert port == 7431
    assert url == "https://box.vesta.run/agents/ada/browser/handover.html"


# ── ports + liveness ──────────────────────────────────────────


def test_free_port_returns_a_bindable_port():
    port = handover._free_port(handover.VNC_PORT_START)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))  # actually free
    finally:
        s.close()


def test_free_display_skips_live_seats(monkeypatch):
    # A real desktop seat (:0/:1) already has a LIVE X server; handover must never pick it, else
    # x11vnc grabs the live seat and noVNC hangs. :99 and :100 answer; it must land on :101.
    monkeypatch.setattr(handover.launcher, "_x_display_reachable", lambda disp: disp in {":99", ":100"})
    assert handover._free_display() == ":101"


def test_alive_false_for_none_and_dead_pid():
    assert handover._alive(None) is False
    # PID 2**31-1 is not a running process on any sane system.
    assert handover._alive(2**31 - 1) is False


# ── teardown ──────────────────────────────────────────────────


def test_stop_is_idempotent_with_nothing_running():
    assert handover.stop() == {"stopped": True}
    assert handover.stop() == {"stopped": True}  # second call is a clean no-op


def test_stop_removes_headed_prefs_from_recorded_profile(isolated):
    # start records the profile it used; stop drops the handover-only user.js so later headless
    # launches on that profile don't inherit software-render prefs.
    profile = isolated / "profile"
    profile.mkdir()
    (profile / "user.js").write_text('user_pref("gfx.webrender.software", true);')
    handover._session_file("profile").write_text(str(profile))
    handover.stop()
    assert not (profile / "user.js").exists()


def test_status_all_false_when_idle():
    st = handover.status()
    assert st["browser"] is False
    assert st["openbox"] is False
    assert st["x11vnc"] is False
    assert st["websockify"] is False
    assert st["web_port"] is None
    assert st["page"] is None


# ── display selection: liveness, not file existence ───────────


def test_free_display_reuses_a_dead_display(monkeypatch):
    # Regression: _free_display judged a display taken by its /tmp/.X11-unix/Xn socket FILE, so a
    # dead Xvfb's leftover socket (crash, or a restart that leaves /tmp intact) blocked the number
    # and corpses eventually exhausted the range. Judging by liveness makes a dead display reusable.
    monkeypatch.setattr(handover.launcher, "_x_display_reachable", lambda disp: False)
    assert handover._free_display(start=99) == ":99"
