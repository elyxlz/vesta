"""Tests for `app-chat history`: recent-list and --search projections read from the skill's own store."""

import argparse
import json

import pytest
from app_chat_cli import commands
from app_chat_cli.store import Store, store_path


def _seed(tmp_path) -> None:
    store = Store(store_path(tmp_path))
    store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "hello world"})
    store.append({"type": "chat", "ts": "2026-01-01T00:00:01", "text": "goodbye moon"})
    store.close()


def _args(tmp_path, *, search=None, limit=20) -> argparse.Namespace:
    return argparse.Namespace(data_dir=str(tmp_path), search=search, limit=limit)


def test_history_lists_recent_conversation(tmp_path, capsys):
    _seed(tmp_path)

    commands.cmd_history(_args(tmp_path))

    assert json.loads(capsys.readouterr().out) == [
        {"timestamp": "2026-01-01T00:00:00", "role": "user", "content": "hello world"},
        {"timestamp": "2026-01-01T00:00:01", "role": "chat", "content": "goodbye moon"},
    ]


def test_history_search_projects_matches(tmp_path, capsys):
    _seed(tmp_path)

    commands.cmd_history(_args(tmp_path, search="goodbye"))

    assert json.loads(capsys.readouterr().out) == [
        {"timestamp": "2026-01-01T00:00:01", "role": "chat", "content": "goodbye moon"},
    ]


def test_history_reports_invalid_search_query(tmp_path, capsys):
    _seed(tmp_path)

    with pytest.raises(SystemExit) as exc:
        commands.cmd_history(_args(tmp_path, search='"bad'))

    assert exc.value.code == 1
    assert "error" in json.loads(capsys.readouterr().out)
