"""Tests for the prompt-based migration runner."""

import json

import core.models as vm
from core.migrations import drop_pending_migrations, list_pending


def _make_config(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    (config.agent_dir / "core" / "migrations").mkdir(parents=True)
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config


def _make_state() -> vm.State:
    return vm.State()


def test_no_migrations_dir_returns_empty(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    assert list_pending(state=_make_state(), config=config) == []


def test_lists_pending_in_filename_order(tmp_path):
    config = _make_config(tmp_path)
    migrations_dir = config.agent_dir / "core" / "migrations"
    (migrations_dir / "002-second.md").write_text("second body")
    (migrations_dir / "001-first.md").write_text("first body")

    pending = list_pending(state=_make_state(), config=config)

    assert [name for name, _ in pending] == ["001-first", "002-second"]
    assert pending[0][1] == "first body"


def test_skips_already_applied(tmp_path):
    config = _make_config(tmp_path)
    migrations_dir = config.agent_dir / "core" / "migrations"
    (migrations_dir / "001-first.md").write_text("first")
    (migrations_dir / "002-second.md").write_text("second")
    state = _make_state()
    state.persisted.applied_migrations = ["001-first"]

    pending = list_pending(state=state, config=config)

    assert [name for name, _ in pending] == ["002-second"]


def test_drop_writes_one_notification_per_migration(tmp_path):
    config = _make_config(tmp_path)
    migrations_dir = config.agent_dir / "core" / "migrations"
    (migrations_dir / "001-first.md").write_text("first body")
    (migrations_dir / "002-second.md").write_text("second body")
    state = _make_state()

    count = drop_pending_migrations(state=state, config=config)

    assert count == 2
    files = sorted(config.notifications_dir.glob("*.json"))
    assert [f.name for f in files] == ["migration-001-first.json", "migration-002-second.json"]
    payload = json.loads(files[0].read_text())
    assert payload["source"] == "core"
    assert payload["type"] == "migration"
    assert payload["interrupt"] is False
    assert "first body" in payload["body"]
    assert "[Migration: 001-first]" in payload["body"]


def test_drop_appends_mark_applied_step_with_correct_name(tmp_path):
    """The runner appends the mark_migration_applied step so authors never hand-write the name."""
    config = _make_config(tmp_path)
    migrations_dir = config.agent_dir / "core" / "migrations"
    (migrations_dir / "001-first.md").write_text("do the thing")
    state = _make_state()

    drop_pending_migrations(state=state, config=config)

    payload = json.loads((config.notifications_dir / "migration-001-first.json").read_text())
    assert 'Call `mark_migration_applied` with `name="001-first"`.' in payload["body"]


def test_drop_no_pending_returns_zero(tmp_path):
    config = _make_config(tmp_path)
    state = _make_state()

    count = drop_pending_migrations(state=state, config=config)

    assert count == 0
    assert list(config.notifications_dir.glob("*.json")) == []


def test_first_start_pre_marks_and_drops_nothing(tmp_path):
    config = _make_config(tmp_path)
    migrations_dir = config.agent_dir / "core" / "migrations"
    (migrations_dir / "001-first.md").write_text("first")
    (migrations_dir / "002-second.md").write_text("second")
    state = _make_state()

    count = drop_pending_migrations(state=state, config=config, first_start=True)

    assert count == 0
    assert list(config.notifications_dir.glob("*.json")) == []
    assert state.persisted.applied_migrations == ["001-first", "002-second"]


def test_legacy_agent_runs_migrations_on_subsequent_boot(tmp_path):
    config = _make_config(tmp_path)
    migrations_dir = config.agent_dir / "core" / "migrations"
    (migrations_dir / "001-first.md").write_text("first body")
    state = _make_state()

    count = drop_pending_migrations(state=state, config=config, first_start=False)

    assert count == 1
    # Drop does NOT pre-mark applied — the agent itself records completion via mark_migration_applied.
    assert state.persisted.applied_migrations == []


def test_redrop_when_agent_did_not_mark_applied(tmp_path):
    """If the agent never called mark_migration_applied (rate limit, crash), the migration runs again on the next boot."""
    config = _make_config(tmp_path)
    migrations_dir = config.agent_dir / "core" / "migrations"
    (migrations_dir / "001-first.md").write_text("first")
    state = _make_state()

    drop_pending_migrations(state=state, config=config, first_start=False)
    assert state.persisted.applied_migrations == []

    # Simulate a boot: clear stale core notifications, then re-derive.
    for f in config.notifications_dir.glob("*.json"):
        f.unlink()

    count = drop_pending_migrations(state=state, config=config, first_start=False)
    assert count == 1, "should re-drop because applied_migrations is still empty"


def test_no_redrop_after_agent_marks_applied(tmp_path):
    """Once the agent has called mark_migration_applied (recorded in state.persisted.applied_migrations), the migration is not re-dropped."""
    config = _make_config(tmp_path)
    migrations_dir = config.agent_dir / "core" / "migrations"
    (migrations_dir / "001-first.md").write_text("first")
    state = _make_state()

    drop_pending_migrations(state=state, config=config, first_start=False)
    # Simulate the agent's mark_migration_applied tool call.
    state.persisted.applied_migrations.append("001-first")
    for f in config.notifications_dir.glob("*.json"):
        f.unlink()

    count = drop_pending_migrations(state=state, config=config, first_start=False)
    assert count == 0
    assert list(config.notifications_dir.glob("*.json")) == []


def test_post_first_start_migration_added_later_runs(tmp_path):
    """A migration shipped after the agent's first boot should still drop."""
    config = _make_config(tmp_path)
    migrations_dir = config.agent_dir / "core" / "migrations"
    (migrations_dir / "001-first.md").write_text("first")
    state = _make_state()

    drop_pending_migrations(state=state, config=config, first_start=True)
    assert state.persisted.applied_migrations == ["001-first"]

    # Later image adds a new migration.
    (migrations_dir / "002-second.md").write_text("second")

    count = drop_pending_migrations(state=state, config=config, first_start=False)

    assert count == 1
    # Drop alone doesn't mark — only the first-start pre-mark is in applied_migrations.
    assert state.persisted.applied_migrations == ["001-first"]
    files = list(config.notifications_dir.glob("migration-002-second.json"))
    assert len(files) == 1
