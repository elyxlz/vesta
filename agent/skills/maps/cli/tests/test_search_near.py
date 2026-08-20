import urllib.parse
from pathlib import Path

from gmaps_cli import client
from gmaps_cli.client import SearchFilters

FIXTURES = Path(__file__).parent / "fixtures"


def _fake_transport(monkeypatch) -> list[str]:
    urls: list[str] = []
    page = (FIXTURES / "search_page.html").read_text(encoding="utf-8")
    feed = (FIXTURES / "search_alghero.json").read_text(encoding="utf-8")

    def fake_get(_client, url: str) -> str:
        urls.append(url)
        return page if "/maps/search/" in url else feed

    monkeypatch.setattr(client, "_get", fake_get)
    return urls


def test_coordinate_near_becomes_a_viewport_not_query_text(monkeypatch):
    urls = _fake_transport(monkeypatch)
    places = client.search("frozen yogurt", near="40.5589,8.3138", filters=SearchFilters(), locale="en-US", country="us")
    assert places
    rpc = next(u for u in urls if "tbm=map" in u)
    query_part, pb_part = rpc.split("&pb=", maxsplit=1)
    assert "!2d8.3138!3d40.5589" in urllib.parse.unquote(pb_part)
    assert "40.5589" not in urllib.parse.unquote(query_part)


def test_place_name_near_stays_in_the_query_text(monkeypatch):
    urls = _fake_transport(monkeypatch)
    client.search("gelateria", near="Alghero, Italy", filters=SearchFilters(), locale="en-US", country="us")
    rpc = next(u for u in urls if "tbm=map" in u)
    query_part, pb_part = rpc.split("&pb=", maxsplit=1)
    assert "Alghero" in urllib.parse.unquote(query_part)
    assert not urllib.parse.unquote(pb_part).startswith("!4m12!1m3!1d")
