"""Tests for the prompt-based migration runner."""

import json
import pathlib as pl
import subprocess
import tarfile

import pytest

import core.config as cfg
import core.models as vm
from core.migrations import (
    MigrationPhase,
    after_sync_migration_turns,
    before_sync_migration_turns,
    list_pending,
)

WORKSPACE_REPAIR_MIGRATION = "2026-08-workspace-repair"
BEFORE_SYNC_FRONTMATTER = "---\nmigration_phase: before_sync\n---\n\n"


def _workspace_repair_text() -> str:
    return (pl.Path(__file__).parents[1] / "core/migrations" / f"{WORKSPACE_REPAIR_MIGRATION}.md").read_text()


def _recovery_script() -> str:
    """The skill-recovery heredoc the migration tells the agent to run, run here for real."""
    return _workspace_repair_text().split("python3 - <<'PY'\n", 1)[1].split("\nPY", 1)[0]


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

    assert [migration.name for migration in pending] == ["001-first", "002-second"]
    assert pending[0].content == "first body"
    assert pending[0].phase is MigrationPhase.AFTER_SYNC


def test_skips_already_applied(mig):
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("first")
    (migrations_dir / "002-second.md").write_text("second")
    state.persisted.applied_migrations = ["001-first"]

    pending = list_pending(state=state, config=config)

    assert [migration.name for migration in pending] == ["002-second"]


def test_returns_all_migrations_in_one_turn_in_order(mig):
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("first body")
    (migrations_dir / "002-second.md").write_text("second body")

    turns = after_sync_migration_turns(state=state, config=config)

    assert len(turns) == 1
    assert "[Migration: 001-first]" in turns[0]
    assert "first body" in turns[0]
    assert "[Migration: 002-second]" in turns[0]
    assert turns[0].index("[Migration: 001-first]") < turns[0].index("[Migration: 002-second]")


def test_declared_phase_splits_migrations_before_and_after_sync(mig):
    config, migrations_dir, state = mig
    (migrations_dir / "001-before.md").write_text(f"{BEFORE_SYNC_FRONTMATTER}before body")
    (migrations_dir / "002-after.md").write_text("---\nmigration_phase: after_sync\n---\n\nafter body")

    [before_turn] = before_sync_migration_turns(state=state, config=config)
    [after_turn] = after_sync_migration_turns(state=state, config=config)

    assert "[Migration: 001-before]" in before_turn
    assert "[Migration: 002-after]" not in before_turn
    assert "migration_phase" not in before_turn
    assert "[Migration: 002-after]" in after_turn
    assert "[Migration: 001-before]" not in after_turn
    assert "migration_phase" not in after_turn


def test_invalid_migration_phase_is_rejected(mig):
    config, migrations_dir, state = mig
    (migrations_dir / "001-invalid.md").write_text("---\nmigration_phase: whenever\n---\n\nbody")

    with pytest.raises(ValueError, match="migration_phase must be one of"):
        list_pending(state=state, config=config)


def test_every_shipped_migration_parses():
    """A malformed shipped migration raises out of collect_boot_turns and crash-loops every agent
    on the boot that ships it, so the whole shipped set must parse here instead."""
    config = cfg.VestaConfig(agent_dir=pl.Path(__file__).parents[1])

    pending = list_pending(state=vm.State(), config=config)

    assert pending, "the shipped migrations dir must not read as empty"
    assert all(migration.phase in set(MigrationPhase) for migration in pending)


def test_blank_frontmatter_lines_are_tolerated(mig):
    config, migrations_dir, state = mig
    (migrations_dir / "001-spaced.md").write_text("---\n\nmigration_phase: before_sync\n\n---\n\nbody")

    [migration] = list_pending(state=state, config=config)

    assert migration.phase is MigrationPhase.BEFORE_SYNC
    assert migration.content.strip() == "body"


def test_before_sync_batch_owns_restart_barrier(mig):
    config, migrations_dir, state = mig
    (migrations_dir / "001-before.md").write_text(f"{BEFORE_SYNC_FRONTMATTER}before body")

    [turn] = before_sync_migration_turns(state=state, config=config)

    assert "Upstream sync is blocked" in turn
    assert "call `restart_vesta` once" in turn
    assert "only proceed to upstream sync" in turn


def test_batch_instructions_keep_stop_local_and_later_boot_tasks_separate(mig):
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("STOP HERE and do not mark applied")
    (migrations_dir / "002-second.md").write_text("second body")

    [turn] = after_sync_migration_turns(state=state, config=config)

    assert "stop only that migration" in turn
    assert "continue with the next migration section" in turn
    assert "Defer any requested `restart_vesta`" in turn
    assert "Do not start other boot" in turn
    assert "tasks yourself" in turn
    assert "[Migration: 002-second]" in turn


def test_appends_mark_applied_step_with_correct_name(mig):
    """The runner appends the mark_migration_applied step so authors never hand-write the name."""
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("do the thing")

    turns = after_sync_migration_turns(state=state, config=config)

    assert 'Call `mark_migration_applied` with `name="001-first"`.' in turns[0]


def test_no_pending_returns_empty(mig):
    config, _migrations_dir, state = mig

    assert after_sync_migration_turns(state=state, config=config) == []


def test_first_start_pre_marks_and_returns_nothing(mig):
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("first")
    (migrations_dir / "002-second.md").write_text("second")

    turns = after_sync_migration_turns(state=state, config=config, first_start=True)

    assert turns == []
    assert state.persisted.applied_migrations == ["001-first", "002-second"]


def test_first_start_pre_marks_complete_set_in_filename_order(mig):
    config, migrations_dir, state = mig
    (migrations_dir / f"{WORKSPACE_REPAIR_MIGRATION}.md").write_text(f"{BEFORE_SYNC_FRONTMATTER}repair")
    (migrations_dir / "002-second.md").write_text("second")

    assert before_sync_migration_turns(state=state, config=config, first_start=True) == []
    assert after_sync_migration_turns(state=state, config=config, first_start=True) == []
    assert state.persisted.applied_migrations == ["002-second", WORKSPACE_REPAIR_MIGRATION]


def test_first_start_pre_marks_both_phases_whichever_getter_runs_first(mig):
    """A fresh agent is born converged, so an unmarked before-sync migration must never survive the
    pre-mark just because the after-sync getter was called first."""
    config, migrations_dir, state = mig
    (migrations_dir / "001-before.md").write_text(f"{BEFORE_SYNC_FRONTMATTER}repair")
    (migrations_dir / "002-second.md").write_text("second")

    assert after_sync_migration_turns(state=state, config=config, first_start=True) == []

    assert state.persisted.applied_migrations == ["001-before", "002-second"]
    assert before_sync_migration_turns(state=state, config=config, first_start=True) == []


def test_workspace_repair_migration_pins_the_pre_sync_recovery_contract():
    text = _workspace_repair_text()

    assert text.startswith(BEFORE_SYNC_FRONTMATTER)
    assert "Do not start upstream sync yourself" in text
    assert ".git-legacy*/info/sparse-checkout" in text
    assert "agent-backup.tar.gz" in text
    assert 'pathlib.Path(".gitignore").write_text("/*\\n!/.gitignore\\n!/agent/\\n/agent/core/\\n")' in text
    # Recovery only unions, so a skill the user switched off after the conversion comes back.
    assert "newly activated" in text
    assert "skills-deactivate" in text


def test_workspace_repair_recovers_active_skills_without_activating_all_stock(tmp_path, monkeypatch):
    home = tmp_path / "home"
    stock_skill = home / "agent/skills/stock"
    stock_skill.mkdir(parents=True)
    (stock_skill / "SKILL.md").write_text("stock")
    subprocess.run(["git", "init", "-q", "-b", "testbox"], cwd=home, check=True)
    subprocess.run(["git", "config", "user.name", "testbox"], cwd=home, check=True)
    subprocess.run(["git", "config", "user.email", "testbox@vesta"], cwd=home, check=True)
    subprocess.run(["git", "add", "agent/skills/stock"], cwd=home, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "stock"], cwd=home, check=True)
    subprocess.run(["git", "tag", "agent-v0.1.180"], cwd=home, check=True)

    config_path = home / "agent/data/config.json"
    config_path.parent.mkdir()
    config_path.write_text('{"active_skills":["existing"]}\n')
    (home / "agent/skills/local-only").mkdir()
    legacy = home / ".git-legacy/info/sparse-checkout"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("/agent/\n!/agent/skills/*/\n/agent/skills/from-cone/\n")

    archived = tmp_path / "archived/agent/skills/from-backup"
    archived.mkdir(parents=True)
    (archived / "SKILL.md").write_text("mine")
    with tarfile.open(home / "agent-backup.tar.gz", "w:gz") as archive:
        archive.add(archived.parents[1], arcname="agent")

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(home)

    exec(compile(_recovery_script(), str(config_path), "exec"), {})

    active = set(json.loads(config_path.read_text())["active_skills"])
    assert active == {"existing", "from-backup", "from-cone", "local-only"}


def test_workspace_repair_skips_local_only_recovery_when_the_stock_list_is_unreadable(tmp_path, monkeypatch):
    """The newest merged tag predates `agent/skills`, so `ls-tree` fails. An empty stock list would
    make every on-disk directory look local-only and activate the whole stock set."""
    home = tmp_path / "home"
    home.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "testbox"], cwd=home, check=True)
    subprocess.run(["git", "config", "user.name", "testbox"], cwd=home, check=True)
    subprocess.run(["git", "config", "user.email", "testbox@vesta"], cwd=home, check=True)
    (home / "MEMORY.md").write_text("memory")
    subprocess.run(["git", "add", "MEMORY.md"], cwd=home, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "pre-skills"], cwd=home, check=True)
    subprocess.run(["git", "tag", "agent-v0.1.180"], cwd=home, check=True)
    stock_skill = home / "agent/skills/stock"
    stock_skill.mkdir(parents=True)
    (stock_skill / "SKILL.md").write_text("stock")
    subprocess.run(["git", "add", "agent/skills/stock"], cwd=home, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "stock"], cwd=home, check=True)

    config_path = home / "agent/data/config.json"
    config_path.parent.mkdir()
    config_path.write_text('{"active_skills":["existing"]}\n')
    (home / "agent/skills/local-only").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(home)

    exec(compile(_recovery_script(), str(config_path), "exec"), {})

    assert json.loads(config_path.read_text())["active_skills"] == ["existing"]


def test_workspace_repair_refuses_to_overwrite_a_corrupt_config(tmp_path, monkeypatch):
    home = tmp_path / "home"
    config_path = home / "agent/data/config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("{broken")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(home)

    with pytest.raises(SystemExit, match="cannot safely read"):
        exec(compile(_recovery_script(), str(config_path), "exec"), {})

    assert config_path.read_text() == "{broken"


def test_legacy_agent_runs_migrations_on_subsequent_boot(mig):
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("first body")

    turns = after_sync_migration_turns(state=state, config=config, first_start=False)

    assert len(turns) == 1
    # Returning a turn does NOT pre-mark applied — the agent records completion via mark_migration_applied.
    assert state.persisted.applied_migrations == []


def test_reruns_when_agent_did_not_mark_applied(mig):
    """If the agent never called mark_migration_applied (rate limit, crash), the migration runs again on the next boot."""
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("first")

    assert len(after_sync_migration_turns(state=state, config=config)) == 1
    assert state.persisted.applied_migrations == []

    # Simulate the next boot: still unmarked, so it re-derives the same turn.
    assert len(after_sync_migration_turns(state=state, config=config)) == 1


def test_no_rerun_after_agent_marks_applied(mig):
    """Once the agent has called mark_migration_applied (recorded in state.persisted.applied_migrations), the migration is not re-run."""
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("first")

    after_sync_migration_turns(state=state, config=config)
    # Simulate the agent's mark_migration_applied tool call.
    state.persisted.applied_migrations.append("001-first")

    assert after_sync_migration_turns(state=state, config=config) == []


def test_post_first_start_migration_added_later_runs(mig):
    """A migration shipped after the agent's first boot should still run."""
    config, migrations_dir, state = mig
    (migrations_dir / "001-first.md").write_text("first")

    after_sync_migration_turns(state=state, config=config, first_start=True)
    assert state.persisted.applied_migrations == ["001-first"]

    # Later image adds a new migration.
    (migrations_dir / "002-second.md").write_text("second")

    turns = after_sync_migration_turns(state=state, config=config, first_start=False)

    assert len(turns) == 1
    assert "[Migration: 002-second]" in turns[0]
    # Returning a turn alone doesn't mark — only the first-start pre-mark is in applied_migrations.
    assert state.persisted.applied_migrations == ["001-first"]
