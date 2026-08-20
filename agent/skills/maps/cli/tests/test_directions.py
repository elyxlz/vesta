from pathlib import Path

from gmaps_cli.directions import build_directions_pb, parse_directions

FIXTURES = Path(__file__).parent / "fixtures"


def test_build_directions_pb_slots_coords_and_mode():
    pb = build_directions_pb((51.5308, -0.1238), (51.5054, -0.0235), "transit")
    assert "3d51.5308!4d-0.1238" in pb
    assert "3d51.5054!4d-0.0235" in pb
    assert "1e3" in pb  # transit mode flag
    assert "{OLAT}" not in pb and "{MODE}" not in pb


def test_build_directions_pb_rejects_bad_mode():
    try:
        build_directions_pb((0.0, 0.0), (1.0, 1.0), "teleport")
    except ValueError:
        return
    raise AssertionError("expected ValueError for bad mode")


def test_parse_directions_driving_has_duration_distance_steps():
    body = (FIXTURES / "dir_driving.txt").read_text(encoding="utf-8")
    leg = parse_directions(body, "driving")
    assert leg.mode == "driving"
    assert leg.duration_text is not None
    assert leg.distance_text is not None
    assert len(leg.steps) >= 1


def test_parse_directions_transit_exposes_line_and_times():
    body = (FIXTURES / "dir_transit.txt").read_text(encoding="utf-8")
    leg = parse_directions(body, "transit")
    transit = [s for s in leg.steps if s.instruction == "transit"]
    assert transit, "expected a transit summary step"
    assert transit[0].line is not None or transit[0].departure is not None
