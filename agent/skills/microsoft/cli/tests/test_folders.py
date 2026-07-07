"""Unit tests for microsoft_cli.folders (mocked Graph calls)."""

import pytest

from microsoft_cli import folders
from microsoft_cli.config import Config

_FOLDERS_PAGE = {
    "value": [
        {
            "id": "inbox-id",
            "displayName": "Inbox",
            "totalItemCount": 10,
            "unreadItemCount": 2,
            "childFolders": [{"id": "sub-id", "displayName": "Receipts", "totalItemCount": 3, "unreadItemCount": 1}],
        },
        {"id": "news-id", "displayName": "Newsletters", "totalItemCount": 5, "unreadItemCount": 5, "childFolders": []},
    ]
}


@pytest.fixture
def patched(monkeypatch):
    calls: list[dict] = []

    def fake_account_id(account_email, cache_file):
        return "acct-1"

    def fake_request(client, cache_file, scopes, base_url, method, path, account_id=None, **kwargs):
        calls.append({"method": method, "path": path, "json": kwargs["json"] if "json" in kwargs else None})
        if method == "GET" and path == "/me/mailFolders":
            return _FOLDERS_PAGE
        if method == "GET" and path.startswith("/me/mailFolders/"):
            return {"id": "inbox-id", "displayName": "Inbox", "totalItemCount": 10, "unreadItemCount": 2}
        if method == "POST":
            return {"id": "created-id", "displayName": "New"}
        return None

    monkeypatch.setattr(folders.auth, "get_account_id_by_email", fake_account_id)
    monkeypatch.setattr(folders.graph, "request", fake_request)
    return calls


def test_list_folders_flattens_children(patched):
    result = folders.list_folders(Config(), None, account_email="me@example.com")
    names = [f["displayName"] for f in result]
    assert names == ["Inbox", "Receipts", "Newsletters"]
    assert result[0] == {"id": "inbox-id", "displayName": "Inbox", "totalItemCount": 10, "unreadItemCount": 2}


def test_resolve_wellknown_key_skips_lookup(patched):
    resolved = folders.resolve_folder_id_cfg(Config(), None, "acct-1", "Archive")
    assert resolved == "archive"
    assert patched == []  # no folder listing needed for a well-known key


def test_resolve_display_name_to_id(patched):
    resolved = folders.resolve_folder_id_cfg(Config(), None, "acct-1", "Newsletters")
    assert resolved == "news-id"
    assert any(c["path"] == "/me/mailFolders" for c in patched)


def test_resolve_unknown_returns_token(patched):
    resolved = folders.resolve_folder_id_cfg(Config(), None, "acct-1", "already-an-id")
    assert resolved == "already-an-id"


def test_folder_status(patched):
    result = folders.folder_status(Config(), None, account_email="me@example.com", folder="inbox")
    assert result["totalItemCount"] == 10
    assert patched[0]["path"] == "/me/mailFolders/inbox"


def test_create_folder_root(patched):
    folders.create_folder(Config(), None, account_email="me@example.com", name="Projects")
    post = [c for c in patched if c["method"] == "POST"][0]
    assert post["path"] == "/me/mailFolders"
    assert post["json"] == {"displayName": "Projects"}


def test_create_folder_nested(patched):
    folders.create_folder(Config(), None, account_email="me@example.com", name="Child", parent_id="parent-id")
    post = [c for c in patched if c["method"] == "POST"][0]
    assert post["path"] == "/me/mailFolders/parent-id/childFolders"


def test_rename_folder(patched):
    folders.rename_folder(Config(), None, account_email="me@example.com", folder_id="fid", name="Renamed")
    patch = [c for c in patched if c["method"] == "PATCH"][0]
    assert patch["path"] == "/me/mailFolders/fid"
    assert patch["json"] == {"displayName": "Renamed"}


def test_delete_folder(patched):
    result = folders.delete_folder(Config(), None, account_email="me@example.com", folder_id="fid")
    assert result == {"status": "deleted", "id": "fid"}
    delete = [c for c in patched if c["method"] == "DELETE"][0]
    assert delete["path"] == "/me/mailFolders/fid"
