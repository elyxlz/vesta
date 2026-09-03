import json
from pathlib import Path

from gmaps_cli.parse import parse_search

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
    assert oops.review_count == 416
    assert oops.phone == "+39 079 966 3707"
    assert oops.open_now is True
    assert oops.category is not None
    assert 40.5 < oops.lat < 40.6
    assert 8.3 < oops.lng < 8.35
    assert oops.links is not None
    assert oops.links.place_url == "https://maps.google.com/?cid=8865181299500082525"


def test_parse_search_reads_a_single_entity_answer():
    # A famous-landmark query gets one entity back, not a list feed; the proto walk finds it too.
    feed = json.loads((FIXTURES / "search_entity_palace.json").read_text(encoding="utf-8"))
    places = parse_search(feed)
    assert len(places) == 1
    palace = places[0]
    assert palace.name == "Buckingham Palace"
    assert palace.cid == 731461058599387815
    assert palace.place_id == "ChIJtV5bzSAFdkgRpwLZFPWrJgo"
    assert palace.review_count is not None and palace.review_count > 100_000
    assert 51.4 < palace.lat < 51.6
    assert -0.2 < palace.lng < -0.1
