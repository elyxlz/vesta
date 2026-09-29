from pathlib import Path

from gmaps_cli.directions import build_pb, parse_directions, transit_time_block

FIXTURES = Path(__file__).parent / "fixtures"


def test_build_pb_slots_coords_and_mode():
    pb = build_pb((51.5308, -0.1238), (51.5054, -0.0235), "walking")
    assert "3d51.5308!4d-0.1238" in pb
    assert "3d51.5054!4d-0.0235" in pb
    assert "1e2" in pb  # walking mode flag
    assert "{OLAT}" not in pb and "{MODE}" not in pb


def test_build_pb_rejects_bad_mode():
    try:
        build_pb((0.0, 0.0), (1.0, 1.0), "teleport")
    except ValueError:
        return
    raise AssertionError("expected ValueError for bad mode")


def test_transit_time_block():
    assert transit_time_block(None, None) == ""
    assert transit_time_block("depart", 1787221190) == "!19m3!1e0!2e2!3j1787221190"
    assert transit_time_block("arrive", 1787221190) == "!19m3!1e1!2e2!3j1787221190"


def test_build_pb_transit_injects_time_block():
    pb = build_pb((51.5308, -0.1238), (51.5054, -0.0235), "transit", time_kind="depart", epoch=1787221190)
    assert "!19m3!1e0!2e2!3j1787221190!20m5!1e3" in pb
    assert "{TIME_BLOCK}" not in pb


def test_build_pb_transit_no_time_leaves_block_empty():
    pb = build_pb((51.5308, -0.1238), (51.5054, -0.0235), "transit")
    assert "{TIME_BLOCK}" not in pb
    assert "!20m5!1e3" in pb


def test_parse_directions_driving_has_duration_distance_steps():
    body = (FIXTURES / "dir_driving.txt").read_text(encoding="utf-8")
    leg = parse_directions(body, "driving")
    assert leg.mode == "driving"
    assert leg.duration_text is not None
    assert leg.distance_text is not None
    assert len(leg.steps) >= 1


def test_parse_directions_transit_has_duration():
    body = (FIXTURES / "dir_transit.txt").read_text(encoding="utf-8")
    leg = parse_directions(body, "transit")
    assert leg.duration_text == "47 min"
    assert leg.distance_text == "5.9 miles"
    assert [s.line for s in leg.steps if s.line] == ["N63", "N550"]


def test_parse_directions_transit_reads_lines_stops_and_totals():
    body = (FIXTURES / "dir_transit_tube.txt").read_text(encoding="utf-8")
    leg = parse_directions(body, "transit")
    assert (leg.duration_text, leg.distance_text) == ("35 min", "7.7 miles")
    assert (leg.depart, leg.arrive, leg.fare) == ("3:12 PM", "3:47 PM", "£3.10")
    rides = [s for s in leg.steps if s.line]
    assert [s.line for s in rides] == ["Jubilee", "Central"]
    jubilee = rides[0]
    assert (jubilee.vehicle, jubilee.headsign) == ("Underground", "Stanmore")
    assert (jubilee.from_stop, jubilee.to_stop, jubilee.num_stops) == ("Southwark", "Bond Street", 4)
    assert (jubilee.depart, jubilee.arrive) == ("3:16 PM", "3:22 PM")
    assert leg.steps[0].instruction == "Walk 4 min (0.1 mi) to Southwark"


def test_parse_directions_driving_steps_are_plain_text():
    body = (FIXTURES / "dir_driving.txt").read_text(encoding="utf-8")
    leg = parse_directions(body, "driving")
    assert (leg.duration_text, leg.distance_text) == ("36 min", "6.4 miles")
    assert leg.steps[1].instruction == "Turn left onto Pancras Rd/A5202"
    assert all("<" not in s.instruction and s.instruction for s in leg.steps)


def test_parse_directions_falls_back_to_scrape_when_structure_drifts():
    leg = parse_directions('[[null, [["x"]]], "12 min", "1.0 km", "Turn left"]', "walking")
    assert (leg.duration_text, leg.distance_text) == ("12 min", "1.0 km")
    assert [s.instruction for s in leg.steps] == ["Turn left"]
