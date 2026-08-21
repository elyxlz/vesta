import json
from pathlib import Path

from gmaps_cli import browser_bridge, lists
from gmaps_cli.models import MapList, MapListItem

_FIX = Path(__file__).parent / "fixtures"


def test_maplist_to_json_roundtrips_fields():
    lst = MapList(id="abc", name="Restaurants", kind=1, item_count=69, share_url="https://maps/x")
    assert lst.to_json() == {"id": "abc", "name": "Restaurants", "kind": 1, "item_count": 69, "share_url": "https://maps/x"}


def test_maplistitem_to_json_allows_null_note():
    item = MapListItem(name="Dishoom", cid=123, note=None)
    assert item.to_json() == {"name": "Dishoom", "cid": 123, "note": None}


def test_list_all_parses_index(monkeypatch):
    payload = json.loads((_FIX / "entitylist_index.json").read_text())
    monkeypatch.setattr(browser_bridge, "entitylist_get", lambda op, pb: payload)
    out = lists.list_all()
    assert [(m.id, m.name, m.kind) for m in out] == [("sys_fav", "Favorite places", 2), ("usr_rest", "Restaurants", 1)]
    assert out[1].share_url == "https://www.google.com/maps/placelists/list/usr_rest"


def test_get_list_parses_items(monkeypatch):
    payload = json.loads((_FIX / "entitylist_getlist.json").read_text())
    monkeypatch.setattr(browser_bridge, "entitylist_get", lambda op, pb: payload)
    items = lists.get_list("usr_rest")
    assert [(i.name, i.cid, i.note) for i in items] == [("Dishoom", 200, "great naan"), ("Padella", 400, None)]
