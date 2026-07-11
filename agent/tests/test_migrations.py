"""Tests for the prompt-based migration runner."""

import pytest

import core.models as vm
import core.config as cfg
from core.migrations import list_pending, pending_migration_turns


@pytest.fixture
def mig(tmp_path):
    """A config with an empty migrations dir on disk, plus a fresh State."""
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    migrations_dir = config.agent_dir / "core" / "migrations"
    migrations_dir.mkdir(parents=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config, migrations_dir, vm.State()


def test_no_migrations_dir_returns_empty(tmp_path):
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    assert list_pending(state=vm.State(), config=config) == []


def test_lists_pending_in_filename_order(mig):
    config, migrations_dir, state = mig
    (migrations_dir / "002-second.md").write_text("second body")
    (migrations_dir / "001-first.md").write_text("first body")

    pending = list_pending(state=state, config=config)

    assert [name for name, _ in pending] == ["001-first", "002-second"]
    assert pending[0][1] == "first body"


def test_skips_already_applied(mig):
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("first")
    (migrations_dir / "002-second.md").write_text("second")
    state.persisted.applied_migrations = ["001-first"]

    pending = list_pending(state=state, config=config)

    assert [name for name, _ in pending] == ["002-second"]


def test_returns_one_turn_per_migration_in_order(mig):
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("first body")
    (migrations_dir / "002-second.md").write_text("second body")

    turns = pending_migration_turns(state=state, config=config)

    assert len(turns) == 2
    assert "[Migration: 001-first]" in turns[0]
    assert "first body" in turns[0]
    assert "[Migration: 002-second]" in turns[1]


def test_appends_mark_applied_step_with_correct_name(mig):
    """The runner appends the mark_migration_applied step so authors never hand-write the name."""
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("do the thing")

    turns = pending_migration_turns(state=state, config=config)

    assert 'Call `mark_migration_applied` with `name="001-first"`.' in turns[0]


def test_no_pending_returns_empty(mig):
    config, _migrations_dir, state = mig

    assert pending_migration_turns(state=state, config=config) == []


def test_first_start_pre_marks_and_returns_nothing(mig):
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("first")
    (migrations_dir / "002-second.md").write_text("second")

    turns = pending_migration_turns(state=state, config=config, first_start=True)

    assert turns == []
    assert state.persisted.applied_migrations == ["001-first", "002-second"]


def test_legacy_agent_runs_migrations_on_subsequent_boot(mig):
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("first body")

    turns = pending_migration_turns(state=state, config=config, first_start=False)

    assert len(turns) == 1
    # Returning a turn does NOT pre-mark applied — the agent records completion via mark_migration_applied.
    assert state.persisted.applied_migrations == []


def test_reruns_when_agent_did_not_mark_applied(mig):
    """If the agent never called mark_migration_applied (rate limit, crash), the migration runs again on the next boot."""
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("first")

    assert len(pending_migration_turns(state=state, config=config)) == 1
    assert state.persisted.applied_migrations == []

    # Simulate the next boot: still unmarked, so it re-derives the same turn.
    assert len(pending_migration_turns(state=state, config=config)) == 1


def test_no_rerun_after_agent_marks_applied(mig):
    """Once the agent has called mark_migration_applied (recorded in state.persisted.applied_migrations), the migration is not re-run."""
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("first")

    pending_migration_turns(state=state, config=config)
    # Simulate the agent's mark_migration_applied tool call.
    state.persisted.applied_migrations.append("001-first")

    assert pending_migration_turns(state=state, config=config) == []


def test_post_first_start_migration_added_later_runs(mig):
    """A migration shipped after the agent's first boot should still run."""
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("first")

    pending_migration_turns(state=state, config=config, first_start=True)
    assert state.persisted.applied_migrations == ["001-first"]

    # Later image adds a new migration.
    (migrations_dir / "002-second.md").write_text("second")

    turns = pending_migration_turns(state=state, config=config, first_start=False)

    assert len(turns) == 1
    assert "[Migration: 002-second]" in turns[0]
    # Returning a turn alone doesn't mark — only the first-start pre-mark is in applied_migrations.
    assert state.persisted.applied_migrations == ["001-first"]
