"""Unit tests for microsoft_cli.notify (real temp file, mocked Graph folder lookup)."""

import json

import pytest

from microsoft_cli import notify, folders
from microsoft_cli.config import Config

_FOLDERS_PAGE = {
    "value": [
        {"id": "inbox-id", "displayName": "Inbox", "childFolders": []},
        {"id": "news-id", "displayName": "Newsletters", "childFolders": []},
    ]
}


@pytest.fixture
def cfg(tmp_path):
    return Config(data_dir=tmp_path)


@pytest.fixture
def patched(monkeypatch):
    def fake_account_id(account_email, cache_file):
        return "acct-1"

    def fake_request(client, cache_file, scopes, base_url, method, path, account_id=None, **kwargs):
        if method == "GET" and path == "/me/mailFolders":
            return _FOLDERS_PAGE
        return None

    monkeypatch.setattr(notify.auth, "get_account_id_by_email", fake_account_id)
    monkeypatch.setattr(folders.graph, "request", fake_request)


def test_default_is_inbox_when_absent(cfg, patched):
    assert notify.get_notify_folders(notify.notify_file_for(cfg), "me@example.com") == ["inbox"]


def test_add_valid_folder_appends_and_persists(cfg, patched):
    result = notify.add_notify(cfg, None, account_email="me@example.com", folder="Newsletters")
    assert result["folders"] == ["inbox", "Newsletters"]
    saved = json.loads(notify.notify_file_for(cfg).read_text())
    assert saved["me@example.com"] == ["inbox", "Newsletters"]


def test_add_is_idempotent(cfg, patched):
    notify.add_notify(cfg, None, account_email="me@example.com", folder="Newsletters")
    result = notify.add_notify(cfg, None, account_email="me@example.com", folder="newsletters")
    assert result["folders"] == ["inbox", "Newsletters"]


def test_add_unknown_folder_rejected(cfg, patched):
    with pytest.raises(ValueError, match="not found on the server"):
        notify.add_notify(cfg, None, account_email="me@example.com", folder="Nonexistent")


def test_add_all_replaces_with_every_folder(cfg, patched):
    result = notify.add_notify(cfg, None, account_email="me@example.com", all_folders=True)
    assert result["folders"] == ["Inbox", "Newsletters"]


def test_remove_folder(cfg, patched):
    notify.add_notify(cfg, None, account_email="me@example.com", folder="Newsletters")
    result = notify.remove_notify(cfg, None, account_email="me@example.com", folder="inbox")
    assert result["folders"] == ["Newsletters"]


def test_remove_last_mutes_account(cfg, patched):
    result = notify.remove_notify(cfg, None, account_email="me@example.com", folder="inbox")
    assert result["folders"] == []
