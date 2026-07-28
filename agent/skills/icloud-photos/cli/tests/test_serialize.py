"""Unit tests for icloud_cli album serialization (pure, no network)."""

from icloud_cli import cli


class FakeAlbum:
    def __init__(self, count=None, **attrs):
        self._count = count
        for key, value in attrs.items():
            setattr(self, key, value)

    def __len__(self):
        if self._count is None:
            raise TypeError("album has no length")
        return self._count


def test_serialize_shared_full():
    album = FakeAlbum(count=12, name="Trip", id="abc", sharing_type="public")
    assert cli._serialize_album(album, "shared") == {
        "name": "Trip",
        "id": "abc",
        "kind": "shared",
        "sharing_type": "public",
        "photo_count": 12,
    }


def test_serialize_shared_missing_attrs_and_count_error():
    album = FakeAlbum(count=None)
    entry = cli._serialize_album(album, "shared")
    assert entry["name"] is None
    assert entry["id"] is None
    assert entry["kind"] == "shared"
    assert entry["sharing_type"] is None
    assert "photo_count" not in entry
    assert entry["photo_count_error"].startswith("TypeError:")


def test_serialize_owned_uses_name():
    album = FakeAlbum(count=3, name="Family", id="xyz")
    assert cli._serialize_album(album, "owned") == {
        "name": "Family",
        "id": "xyz",
        "kind": "owned",
        "photo_count": 3,
    }


def test_serialize_owned_falls_back_to_title():
    album = FakeAlbum(count=0, name=None, title="Recents", id="r1")
    assert cli._serialize_album(album, "owned") == {
        "name": "Recents",
        "id": "r1",
        "kind": "owned",
        "photo_count": 0,
    }


def test_serialize_owned_has_no_sharing_type():
    album = FakeAlbum(count=1, name="Owned", id="o1")
    assert "sharing_type" not in cli._serialize_album(album, "owned")
