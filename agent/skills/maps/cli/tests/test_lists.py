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


def test_get_list_normalises_signed_cid_to_unsigned(monkeypatch):
    # getlist gives ftid halves as signed 64-bit decimals; a negative low half must fold to unsigned.
    signed_low = "-7008812868250662403"
    item = [None, [None, None, "addr", None, "a2", [None, None, 1.0, 2.0], ["100", signed_low], "/g/x"], "Hotel", "", None, None, None, [], [[1], ["100", signed_low]]]
    monkeypatch.setattr(browser_bridge, "entitylist_get", lambda op, pb: [[["usr_rest", 1], 1, None, None, "R", "", None, None, [item]]])
    items = lists.get_list("usr_rest")
    assert items[0].cid == int(signed_low) % (2**64)
    assert items[0].cid > 0
