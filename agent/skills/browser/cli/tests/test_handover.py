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
    with pytest.raises(RuntimeError, match="x11vnc, websockify, openbox"):
        handover._require_binaries()


def test_require_binaries_ok_when_present(monkeypatch):
    monkeypatch.setattr(handover.shutil, "which", lambda name: f"/usr/bin/{name}")
    handover._require_binaries()  # does not raise


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
