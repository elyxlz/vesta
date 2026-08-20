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
    proc = _run(["directions", "Canary Wharf, London", "--mode", "walking"])
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["mode"] == "walking"
    assert "travelmode=walking" in out["directions_url"]
    assert "Canary" in out["directions_url"]  # named destination, not coordinates
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
