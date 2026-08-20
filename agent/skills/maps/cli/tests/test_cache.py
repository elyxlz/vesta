from gmaps_cli import cache


def test_put_get_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAPS_CACHE_DIR", str(tmp_path))
    cache.put(cid=123, name="Oops", lat=40.5, lng=8.3, ftid="0xa:0xb", place_id="ChIJx")
    stop = cache.get(123)
    assert stop is not None
    assert stop.name == "Oops"
    assert stop.place_id == "ChIJx"
    assert stop.ftid == "0xa:0xb"
    assert stop.lat == 40.5
    assert stop.lng == 8.3


def test_get_miss_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAPS_CACHE_DIR", str(tmp_path))
    assert cache.get(999) is None


def test_corrupt_cache_reads_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAPS_CACHE_DIR", str(tmp_path))
    (tmp_path / "places.json").write_text("{ not json", encoding="utf-8")
    assert cache.get(123) is None


def test_wrong_shape_cache_reads_empty_and_is_rebuilt(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAPS_CACHE_DIR", str(tmp_path))
    (tmp_path / "places.json").write_text('{"123": {"ts": "not-a-number"}, "456": [1, 2]}', encoding="utf-8")
    assert cache.get(123) is None
    cache.put(cid=123, name="Oops", lat=40.5, lng=8.3, ftid=None, place_id=None)
    stop = cache.get(123)
    assert stop is not None
    assert stop.name == "Oops"
