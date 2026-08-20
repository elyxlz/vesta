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


def test_directions_emits_named_link_json():
    to = json.dumps({"name": "Canary Wharf, London", "place_id": "ChIJcanary", "lat": 51.5054, "lng": -0.0235})
    proc = _run(["directions", "--to", to, "--mode", "walking"])
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["mode"] == "walking"
    assert "travelmode=walking" in out["directions_url"]
    assert "destination_place_id=ChIJcanary" in out["directions_url"]  # exact place, not a pin
    assert "note" in out


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
