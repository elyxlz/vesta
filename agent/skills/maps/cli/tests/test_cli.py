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
