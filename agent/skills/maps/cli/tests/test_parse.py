import json
from pathlib import Path

from gmaps_cli.parse import parse_directions, parse_search

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_search_returns_places():
    feed = json.loads((FIXTURES / "search_alghero.json").read_text(encoding="utf-8"))
    places = parse_search(feed)
    assert len(places) >= 6
    by_name = {p.name: p for p in places}
    oops = by_name["Alghero Gelateria Oops"]
    assert oops.address == "Via delle Baleari, 53, 07041 Alghero SS, Italy"
    assert oops.cid == 8865181299500082525
    assert oops.ftid == "0x12dcf1f90bb8a3c3:0x7b07736c1223655d"
    assert oops.rating == 4.7
    assert oops.category is not None
    assert 40.5 < oops.lat < 40.6
    assert 8.3 < oops.lng < 8.35
    assert oops.links is not None
    assert oops.links.place_url == "https://maps.google.com/?cid=8865181299500082525"


def test_parse_directions_driving_has_distance_and_steps():
    body = (FIXTURES / "dir_driving.txt").read_text(encoding="utf-8")
    leg = parse_directions(body, "driving")
    assert leg.mode == "driving"
    assert leg.distance_text is not None
    assert leg.duration_text is not None
    assert len(leg.steps) >= 1


def test_parse_directions_transit_exposes_line_and_times():
    body = (FIXTURES / "dir_transit_london.txt").read_text(encoding="utf-8")
    leg = parse_directions(body, "transit")
    transit_steps = [s for s in leg.steps if s.instruction == "transit"]
    assert transit_steps, "expected a transit summary step"
    head = transit_steps[0]
    assert head.line is not None or head.departure is not None
