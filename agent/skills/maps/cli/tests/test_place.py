from pathlib import Path

from gmaps_cli.place import build_place_pb, build_reverse_pb, parse_place, parse_reverse

FIXTURES = Path(__file__).parent / "fixtures"
OOPS_CID = 8865181299500082525


def test_build_place_pb_slots_cid_hex():
    pb = build_place_pb(OOPS_CID)
    assert format(OOPS_CID, "x") in pb
    assert "{CID_HEX}" not in pb


def test_parse_place_extracts_detail():
    body = (FIXTURES / "place_oops.txt").read_text(encoding="utf-8")
    place = parse_place(body, OOPS_CID)
    assert place.name == "Alghero Gelateria Oops"
    assert place.place_id == "ChIJw6O4C_nx3BIRXWUjEmxzB3s"
    assert place.ftid == "0x12dcf1f90bb8a3c3:0x7b07736c1223655d"
    assert place.phone == "+39 079 966 3707"
    assert place.rating == 4.7
    assert place.website is not None and "facebook" in place.website
    assert place.hours_today is not None
    assert place.open_intervals == [(660, 1440)]  # 11 am-12 am
    assert place.lat is not None and 40.5 < place.lat < 40.6
    assert place.lng is not None and 8.3 < place.lng < 8.35
    assert place.links is not None
    assert place.links.place_url == "https://maps.google.com/?cid=8865181299500082525"


def test_build_reverse_pb_slots_coords():
    pb = build_reverse_pb(41.9028, 12.4964)
    assert "41.9028,12.4964" in pb
    assert "{COORDS}" not in pb


def test_parse_reverse_returns_label():
    body = (FIXTURES / "reverse_rome.txt").read_text(encoding="utf-8")
    label = parse_reverse(body)
    assert label is not None
    assert "Rome" in label
