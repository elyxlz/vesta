"""Tests for the prompt-based migration runner."""

import asyncio

import pytest
import core.models as vm
from core.migrations import APPLIED_FILE_NAME, applied_file, list_pending, queue_migrations


def _make_config(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    (config.agent_dir / "core" / "migrations").mkdir(parents=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config


def test_no_migrations_dir_returns_empty(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    assert list_pending(config) == []


def test_lists_pending_in_filename_order(tmp_path):
    config = _make_config(tmp_path)
    migrations_dir = config.agent_dir / "core" / "migrations"
    (migrations_dir / "002-second.md").write_text("second body")
    (migrations_dir / "001-first.md").write_text("first body")

    pending = list_pending(config)

    assert [name for name, _ in pending] == ["001-first", "002-second"]
    assert pending[0][1] == "first body"


def test_skips_already_applied(tmp_path):
    config = _make_config(tmp_path)
    migrations_dir = config.agent_dir / "core" / "migrations"
    (migrations_dir / "001-first.md").write_text("first")
    (migrations_dir / "002-second.md").write_text("second")
    applied_file(config).write_text("001-first\n")

    pending = list_pending(config)

    assert [name for name, _ in pending] == ["002-second"]


def test_applied_file_tolerates_blank_lines(tmp_path):
    config = _make_config(tmp_path)
    migrations_dir = config.agent_dir / "core" / "migrations"
    (migrations_dir / "001-first.md").write_text("first")
    applied_file(config).write_text("\n\n  001-first  \n\n")

    assert list_pending(config) == []


@pytest.mark.anyio
async def test_queue_migrations_enqueues_each(tmp_path):
    config = _make_config(tmp_path)
    migrations_dir = config.agent_dir / "core" / "migrations"
    (migrations_dir / "001-first.md").write_text("first body")
    (migrations_dir / "002-second.md").write_text("second body")
    queue: asyncio.Queue = asyncio.Queue()

    count = await queue_migrations(queue, config=config)

    assert count == 2
    msg1, is_user1 = await queue.get()
    msg2, is_user2 = await queue.get()
    assert is_user1 is False and is_user2 is False
    assert "[Migration: 001-first]" in msg1 and "first body" in msg1
    assert "[Migration: 002-second]" in msg2 and "second body" in msg2


@pytest.mark.anyio
async def test_queue_migrations_no_pending_returns_zero(tmp_path):
    config = _make_config(tmp_path)
    queue: asyncio.Queue = asyncio.Queue()

    count = await queue_migrations(queue, config=config)

    assert count == 0
    assert queue.empty()


def test_applied_file_path_uses_data_dir(tmp_path):
    config = _make_config(tmp_path)
    assert applied_file(config) == config.data_dir / APPLIED_FILE_NAME
