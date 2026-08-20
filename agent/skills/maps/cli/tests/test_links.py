from gmaps_cli.links import (
    Stop,
    cid_from_ftid,
    directions_url,
    place_url,
    route_url,
)


def test_cid_from_ftid():
    assert cid_from_ftid("0x12dcf1f90bb8a3c3:0x7b07736c1223655d") == 8865181299500082525


def test_place_url():
    assert place_url(8865181299500082525) == "https://maps.google.com/?cid=8865181299500082525"


def test_directions_url_no_origin():
    url = directions_url((40.5748, 8.317), mode="walking")
    assert "api=1" in url
    assert "travelmode=walking" in url
    assert "destination=40.5748%2C8.317" in url
    assert "origin=" not in url


def test_directions_url_rejects_bad_mode():
    try:
        directions_url((1.0, 2.0), mode="teleport")
    except ValueError:
        return
    raise AssertionError("expected ValueError for bad mode")


def test_route_url_named_stops():
    stops = [
        Stop("Oops", 40.5748, 8.317, "ChIJoops"),
        Stop("ReGelato", 40.5579, 8.3138, "ChIJre"),
        Stop("K2", 40.5586, 8.3147, "ChIJk2"),
    ]
    url = route_url(stops, mode="walking")
    assert "origin_place_id=ChIJoops" in url
    assert "destination_place_id=ChIJk2" in url
    assert "waypoints=ReGelato" in url
    assert "waypoint_place_ids=ChIJre" in url


def test_route_url_needs_two_stops():
    try:
        route_url([Stop("only", 1.0, 2.0)], mode="driving")
    except ValueError:
        return
    raise AssertionError("expected ValueError for single stop")
