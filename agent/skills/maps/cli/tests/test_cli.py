import json
import subprocess
import sys


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "gmaps_cli.cli", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_directions_by_cid_uses_cached_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAPS_CACHE_DIR", str(tmp_path))
    from gmaps_cli import cache

    cache.put(cid=8865181299500082525, name="Canary Wharf", lat=51.5054, lng=-0.0235, ftid="0x1:0x2", place_id="ChIJcanary")
    proc = _run(["directions", "--to", "8865181299500082525", "--mode", "walking"])
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["mode"] == "walking"
    assert "travelmode=walking" in out["directions_url"]
    assert "destination_place_id=ChIJcanary" in out["directions_url"]  # exact place, not a pin


def test_route_named_multistop_link():
    stops = json.dumps(
        [
            {"name": "Oops", "lat": 40.5748, "lng": 8.317, "place_id": "ChIJoops"},
            {"name": "K2", "lat": 40.5586, "lng": 8.3147, "place_id": "ChIJk2"},
        ]
    )
    proc = _run(["route", "--stops", stops, "--mode", "walking"])
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["stops"] == 2
    assert "origin_place_id=ChIJoops" in out["route_url"]


def test_error_goes_to_stderr_nonzero():
    proc = _run(["route", "--stops", "not-json"])
    assert proc.returncode != 0
    assert proc.stdout.strip() == ""
    err = json.loads(proc.stderr)
    assert "error" in err


def test_route_non_object_stops_is_json_error():
    proc = _run(["route", "--stops", "[1, 2]"])
    assert proc.returncode != 0
    assert proc.stdout.strip() == ""
    err = json.loads(proc.stderr)
    assert "error" in err


def test_network_error_is_json_error(monkeypatch, capsys):
    import httpx
    from gmaps_cli import cli

    def boom(*args: object, **kwargs: object) -> object:
        raise httpx.ConnectError("dns down")

    monkeypatch.setattr(cli, "search", boom)
    monkeypatch.setattr(sys, "argv", ["maps", "search", "coffee"])
    assert cli.main() == 1
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    err = json.loads(captured.err)
    assert "network error" in err["error"]


import os
import stat

_SHIM_SIGNED_OUT = """#!/usr/bin/env python3
import json, sys
code = sys.stdin.read()
if "maps/search/coffee" in code:
    stdout = json.dumps({"session_token": "", "pool": []})  # no token: writes read signed-out
else:
    stdout = json.dumps({"signed_in": False, "status": 302, "body": ""})
envelope = {"schema": "browser.result.v1", "ok": True, "warnings": [],
    "output": {"stdout": stdout, "stderr": "", "exit_code": 0, "duration_ms": 1}}
sys.stdout.write(json.dumps(envelope))
"""


def _install_browser_shim(tmp_path, body, monkeypatch):
    shim = tmp_path / "browser"
    shim.write_text(body)
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("MAPS_BROWSER_BIN", str(shim))


def test_lists_signed_out_returns_sign_in_required(tmp_path, monkeypatch):
    _install_browser_shim(tmp_path, _SHIM_SIGNED_OUT, monkeypatch)
    proc = subprocess.run(
        [sys.executable, "-m", "gmaps_cli.cli", "lists"],
        capture_output=True,
        text=True,
        env=dict(os.environ),
        check=False,
    )
    assert proc.returncode != 0
    assert proc.stdout.strip() == ""
    err = json.loads(proc.stderr)
    assert err["error"] == "sign_in_required"
    assert "accounts.google.com" in err["url"]


def test_write_verbs_require_sign_in(tmp_path, monkeypatch):
    _install_browser_shim(tmp_path, _SHIM_SIGNED_OUT, monkeypatch)
    for argv in (["lists", "create", "x"], ["lists", "rename", "x", "y"], ["lists", "delete", "x"]):
        proc = subprocess.run(
            [sys.executable, "-m", "gmaps_cli.cli", *argv],
            capture_output=True,
            text=True,
            env=dict(os.environ),
            check=False,
        )
        assert proc.returncode != 0
        assert json.loads(proc.stderr)["error"] == "sign_in_required"


def test_add_remove_require_sign_in_with_cached_place(tmp_path, monkeypatch):
    # Seed the identity cache so cid resolution needs no network; the write then hits signed-out.
    monkeypatch.setenv("GMAPS_CACHE_DIR", str(tmp_path))
    from gmaps_cli import cache

    cache.put(cid=1, name="Somewhere", lat=51.5, lng=-0.1, ftid="0x2:0x1", place_id="p")
    _install_browser_shim(tmp_path, _SHIM_SIGNED_OUT, monkeypatch)
    for argv in (["lists", "add", "x", "1"], ["lists", "remove", "x", "1"]):
        proc = subprocess.run(
            [sys.executable, "-m", "gmaps_cli.cli", *argv],
            capture_output=True,
            text=True,
            env=dict(os.environ),
            check=False,
        )
        assert proc.returncode != 0
        assert json.loads(proc.stderr)["error"] == "sign_in_required"
