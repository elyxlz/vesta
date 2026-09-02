"""Saved email bodies are partitioned by account, so `auth remove` deletes exactly that account's cache."""

import pathlib as pl
from unittest.mock import MagicMock

from microsoft_cli import auth, auth_commands, email
from microsoft_cli.config import Config


def _message(subject: str) -> dict:
    return {
        "subject": subject,
        "from": {"emailAddress": {"address": "sender@example.com"}},
        "body": {"contentType": "Text", "content": "hello"},
    }


def _app_with(username: str) -> MagicMock:
    app = MagicMock()
    app.get_accounts.return_value = [{"username": username, "home_account_id": "id-1"}]
    return app


def test_body_is_saved_under_the_lowercased_account_directory(tmp_path):
    config = Config(data_dir=tmp_path)

    result = email.finalize_email_body(config, "Me@Example.com", "msg-1", _message("Hi"), None)

    saved = pl.Path(result["body_saved_to"])
    assert saved.parent == tmp_path / "emails" / "me_example_com"
    assert saved.read_text().endswith("hello")


def test_remove_account_deletes_only_that_accounts_cached_bodies(tmp_path, monkeypatch):
    config = Config(data_dir=tmp_path)
    monkeypatch.setattr(auth, "get_app", lambda *a, **k: _app_with("me@example.com"))
    email.finalize_email_body(config, "me@example.com", "msg-1", _message("one"), None)
    email.finalize_email_body(config, "me@example.com", "msg-2", _message("two"), None)
    email.finalize_email_body(config, "other@example.com", "msg-3", _message("three"), None)

    result = auth_commands.remove_account(config, account_email="Me@Example.com")

    assert result == {"status": "removed", "email": "Me@Example.com", "cached_bodies_deleted": 2}
    assert not (tmp_path / "emails" / "me_example_com").exists()
    assert len(list((tmp_path / "emails" / "other_example_com").iterdir())) == 1


def test_remove_account_with_no_cached_bodies_reports_zero(tmp_path, monkeypatch):
    config = Config(data_dir=tmp_path)
    monkeypatch.setattr(auth, "get_app", lambda *a, **k: _app_with("me@example.com"))

    result = auth_commands.remove_account(config, account_email="me@example.com")

    assert result["cached_bodies_deleted"] == 0
