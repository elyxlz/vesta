import json
from pathlib import Path

from gmaps_cli.parse import _first_rating, parse_search

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


def test_rating_skips_coordinate_band_floats():
    # A Paris-like coordinate (lng 2.35, lat 48.85) sits in the rating band but must be skipped.
    record = [[None, 2.35, 48.85], 4.6]
    assert _first_rating(record) == 4.6
    assert _first_rating([[None, 2.35, 48.85]]) is None
