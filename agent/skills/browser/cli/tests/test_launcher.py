"""Unit tests for the Camoufox launcher (fetch, verify, extract, ws parsing)."""

from __future__ import annotations

import hashlib
import zipfile

import pytest

from vesta_browser import launcher


def test_assets_cover_both_linux_arches():
    assert set(launcher.CAMOUFOX_ASSETS) == {"aarch64", "x86_64"}
    for name, sha in launcher.CAMOUFOX_ASSETS.values():
        assert name.endswith(".zip")
        assert len(sha) == 64


def test_asset_for_arch_known(monkeypatch):
    monkeypatch.setattr(launcher.platform, "machine", lambda: "x86_64")
    name, sha = launcher._asset_for_arch()
    assert "x86_64" in name
    assert len(sha) == 64


def test_asset_for_arch_unknown(monkeypatch):
    monkeypatch.setattr(launcher.platform, "machine", lambda: "sparc64")
    with pytest.raises(RuntimeError, match="no Camoufox build"):
        launcher._asset_for_arch()


def test_camoufox_home_uses_release_tag():
    assert launcher.CAMOUFOX_RELEASE_TAG in str(launcher.camoufox_home())


def test_ensure_camoufox_honors_override(tmp_path):
    exe = tmp_path / "camoufox"
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    assert launcher.ensure_camoufox(str(exe)) == str(exe)


def test_ensure_camoufox_rejects_missing_override(tmp_path):
    with pytest.raises(RuntimeError, match="executable not found"):
        launcher.ensure_camoufox(str(tmp_path / "does-not-exist"))


def test_verify_sha256_ok(tmp_path):
    f = tmp_path / "blob"
    f.write_bytes(b"hello world")
    launcher._verify_sha256(f, hashlib.sha256(b"hello world").hexdigest())


def test_verify_sha256_mismatch(tmp_path):
    f = tmp_path / "blob"
    f.write_bytes(b"hello world")
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        launcher._verify_sha256(f, "0" * 64)


def test_extract_preserving_mode_restores_exec_bit(tmp_path):
    zpath = tmp_path / "a.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        info = zipfile.ZipInfo("camoufox")
        info.external_attr = 0o755 << 16
        z.writestr(info, "#!/bin/sh\n")
        z.writestr("data.txt", "plain")
    dest = tmp_path / "out"
    launcher._extract_preserving_mode(zpath, dest)
    assert (dest / "camoufox").stat().st_mode & 0o100  # owner-exec restored
    assert (dest / "data.txt").read_text() == "plain"


def _dummy_proc(returncode):
    class Proc:
        def poll(self):
            return returncode

    proc = Proc()
    proc.returncode = returncode
    return proc


def test_read_ws_url_parses_and_appends_session(tmp_path):
    log = tmp_path / "log"
    log.write_text("Marionette boot\nWebDriver BiDi listening on ws://127.0.0.1:5555\nmore\n")
    url = launcher._read_ws_url(_dummy_proc(None), log, timeout_s=1.0)
    assert url == "ws://127.0.0.1:5555/session"


def test_read_ws_url_raises_when_proc_exits(tmp_path):
    log = tmp_path / "log"
    log.write_text("boot failure, no bidi\n")
    with pytest.raises(RuntimeError, match="exited"):
        launcher._read_ws_url(_dummy_proc(1), log, timeout_s=1.0)


def test_read_ws_url_times_out(tmp_path):
    log = tmp_path / "log"
    log.write_text("nothing useful here\n")
    with pytest.raises(RuntimeError, match="did not announce"):
        launcher._read_ws_url(_dummy_proc(None), log, timeout_s=0.3)


def test_launch_env_strips_display_when_headless(monkeypatch, tmp_path):
    # Headless Firefox hangs on GTK init if a dead DISPLAY is inherited (e.g. a caller that sets
    # DISPLAY=:99 out of habit), so headless launches must drop it.
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    env = launcher._launch_env(tmp_path, use_headless=True)
    assert "DISPLAY" not in env
    assert "WAYLAND_DISPLAY" not in env
    assert env["MOZ_HEADLESS"] == "1"
    assert any(k.startswith("CAMOU_CONFIG_") for k in env)


def test_launch_env_keeps_display_when_headed(monkeypatch, tmp_path):
    # Handover runs headed under its own Xvfb and needs the display.
    monkeypatch.setenv("DISPLAY", ":99")
    env = launcher._launch_env(tmp_path, use_headless=False)
    assert env["DISPLAY"] == ":99"
    assert "MOZ_HEADLESS" not in env
    assert env["LIBGL_ALWAYS_SOFTWARE"] == "1"  # headed forces software GL (no glxtest helper)


def test_ensure_headed_prefs_forces_software_webrender(tmp_path):
    launcher._ensure_headed_prefs(tmp_path)
    prefs = (tmp_path / "user.js").read_text()
    assert 'gfx.webrender.software", true' in prefs
    # WebGL must stay enabled or Camoufox's spoofed WebGL vendor/renderer would go missing.
    assert "webgl.disabled" not in prefs


def test_ensure_headed_prefs_is_idempotent(tmp_path):
    launcher._ensure_headed_prefs(tmp_path)
    launcher._ensure_headed_prefs(tmp_path)
    assert (tmp_path / "user.js").read_text().count("gfx.webrender.software") == 1
