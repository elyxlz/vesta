"""Unit tests for the Chromium launcher."""

from __future__ import annotations

import json
import socket

import pytest

from vesta_browser import launcher


def test_stealth_args_count():
    # If this drops, Scrapling's defense posture probably weakened — investigate.
    assert len(launcher.STEALTH_ARGS) >= 50


def test_harmful_args_listed():
    # The stealth-mode arg filter drops args that leak automation signals.
    assert "--enable-automation" in launcher.HARMFUL_ARGS
    assert "--disable-popup-blocking" in launcher.HARMFUL_ARGS


def test_find_free_port_returns_int_in_range():
    port = launcher.find_free_port(start=38000, end=38050)
    assert 38000 <= port < 38050


def test_port_free_false_for_bound_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    try:
        assert launcher._port_free(port) is False
    finally:
        s.close()


def test_is_cdp_reachable_false_when_nothing_listens():
    assert launcher.is_cdp_reachable(1, timeout_s=0.1) is False


def test_find_chromium_executable_honors_override(tmp_path):
    exe = tmp_path / "my-chrome"
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    assert launcher.find_chromium_executable(str(exe)) == str(exe)


def test_find_chromium_executable_rejects_missing_override(tmp_path):
    with pytest.raises(RuntimeError, match="executable not found"):
        launcher.find_chromium_executable(str(tmp_path / "does-not-exist"))


def test_ensure_clean_exit_flips_flags(tmp_path):
    default = tmp_path / "Default"
    default.mkdir()
    prefs = default / "Preferences"
    prefs.write_text(json.dumps({"exit_type": "Crashed", "exited_cleanly": False}))

    launcher._ensure_clean_exit(tmp_path)

    data = json.loads(prefs.read_text())
    assert data["exit_type"] == "Normal"
    assert data["exited_cleanly"] is True


def test_ensure_clean_exit_noop_when_prefs_missing(tmp_path):
    # Should not raise when Default/Preferences doesn't exist yet (fresh profile).
    launcher._ensure_clean_exit(tmp_path)


def test_ensure_clean_exit_noop_on_garbage_prefs(tmp_path):
    default = tmp_path / "Default"
    default.mkdir()
    (default / "Preferences").write_text("{ not: json")
    launcher._ensure_clean_exit(tmp_path)


def test_read_ws_url_errors_without_endpoint():
    with pytest.raises(Exception):
        launcher.read_ws_url(1, timeout_s=0.1)
