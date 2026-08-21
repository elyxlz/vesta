from gmaps_cli.models import MapList, MapListItem


def test_maplist_to_json_roundtrips_fields():
    lst = MapList(id="abc", name="Restaurants", kind=1, item_count=69, share_url="https://maps/x")
    assert lst.to_json() == {"id": "abc", "name": "Restaurants", "kind": 1, "item_count": 69, "share_url": "https://maps/x"}


def test_maplistitem_to_json_allows_null_note():
    item = MapListItem(name="Dishoom", cid=123, note=None)
    assert item.to_json() == {"name": "Dishoom", "cid": 123, "note": None}
