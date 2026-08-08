"""Tests for boot-turn assembly: boot-time control-flow delivered as ordered, non-interruptible turns."""

from unittest.mock import patch

from test_upstream_sync_turn import _record_snapshot

import core.config as cfg
import core.models as vm
from core.main import collect_boot_turns
from core.migrations import MIGRATION_BATCH_INSTRUCTIONS
from core.provider import ProviderAuthState, ProviderStatus

BEFORE_SYNC_FRONTMATTER = "---\nmigration_phase: before_sync\n---\n\n"


def _boot_config(tmp_path):
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    for sub in ["core/migrations", "core/prompts", "skills", "data", "dreamer"]:
        (config.agent_dir / sub).mkdir(parents=True, exist_ok=True)
    return config


def _authed_state() -> vm.State:
    # The greeting is gated on an authenticated provider; these tests exercise the assembly, so authenticate.
    state = vm.State()
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")
    return state


def test_boot_turns_ordered_sync_then_migrations_then_config_then_greeting(tmp_path):
    config = _boot_config(tmp_path)
    (config.agent_dir / "core" / "migrations" / "001-x.md").write_text("do migration x")
    (config.agent_dir / "core" / "migrations" / "002-y.md").write_text("do migration y")
    # The running version's snapshot is absent from Git, so the upstream-sync turn fires.
    (config.agent_dir / "core" / "pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "9.9.9"\n')

    turns = collect_boot_turns(
        state=_authed_state(),
        config=config,
        config_issues=["BAD=1 is invalid; reverted to default"],
        agent_message="You restarted after a routine shutdown.",
        first_start=False,
    )

    assert len(turns) == 4
    # No converge turn carries a daemon-restore preamble: the sync turn opens with its own marker and
    # the migration turn with the batch instructions. Daemons come up at the greeting (last), after
    # the sync and migrations have landed, so a migration reshaping the Daemons block runs first.
    assert turns[0].text.startswith("[Upstream sync]")
    assert turns[1].text.startswith(MIGRATION_BATCH_INSTRUCTIONS)
    assert "[Migration: 001-x]" in turns[1].text
    assert "[Migration: 002-y]" in turns[1].text
    assert "BAD=1" in turns[2].text
    assert turns[3].text.startswith("[System Restart]\nReason: You restarted after a routine shutdown.")


def test_before_sync_migrations_are_a_boot_barrier(tmp_path):
    config = _boot_config(tmp_path)
    (config.agent_dir / "core" / "migrations" / "001-before.md").write_text(f"{BEFORE_SYNC_FRONTMATTER}prepare workspace")
    (config.agent_dir / "core" / "migrations" / "999-later.md").write_text("later migration")
    (config.agent_dir / "core" / "pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "9.9.9"\n')

    turns = collect_boot_turns(
        state=_authed_state(),
        config=config,
        config_issues=[],
        agent_message="You restarted after an upgrade.",
        first_start=False,
    )

    # The before-sync barrier turn opens with the batch instructions, no daemon-restore preamble.
    assert turns[0].text.startswith(MIGRATION_BATCH_INSTRUCTIONS)
    assert "[Migration: 001-before]" in turns[0].text
    assert "call `restart_vesta` once" in turns[0].text
    assert all("[Upstream sync]" not in turn.text for turn in turns)
    assert all("[Migration: 999-later]" not in turn.text for turn in turns)


def test_applied_before_sync_migration_allows_sync_then_after_sync_migrations(tmp_path):
    config = _boot_config(tmp_path)
    (config.agent_dir / "core" / "migrations" / "001-before.md").write_text(f"{BEFORE_SYNC_FRONTMATTER}prepare workspace")
    (config.agent_dir / "core" / "migrations" / "999-later.md").write_text("later migration")
    (config.agent_dir / "core" / "pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "9.9.9"\n')
    state = _authed_state()
    state.persisted.applied_migrations = ["001-before"]

    turns = collect_boot_turns(
        state=state,
        config=config,
        config_issues=[],
        agent_message="You restarted after workspace repair.",
        first_start=False,
    )

    assert turns[0].text.startswith("[Upstream sync]")
    assert "[Migration: 999-later]" in turns[1].text


def test_after_sync_migration_boot_defers_daemons_to_the_greeting(tmp_path):
    """After the merge the running version's snapshot is in Git, so no sync turn fires, but the
    after-sync migrations were left for this boot. The migration turn opens with the batch
    instructions, no daemon-restore preamble: daemons come up at the greeting, after the migrations."""
    config = _boot_config(tmp_path)
    (config.agent_dir / "core" / "migrations" / "001-x.md").write_text("do migration x")
    (config.agent_dir / "core" / "pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "9.9.9"\n')
    _record_snapshot(config, "9.9.9")

    turns = collect_boot_turns(
        state=_authed_state(),
        config=config,
        config_issues=[],
        agent_message="You restarted after an upgrade.",
        first_start=False,
    )

    assert len(turns) == 2
    assert turns[0].text.startswith(MIGRATION_BATCH_INSTRUCTIONS)
    assert "[Migration: 001-x]" in turns[0].text
    assert turns[1].text.startswith("[System Restart]")  # greeting is last, the daemon-restore point
    assert all("[Upstream sync]" not in turn.text for turn in turns)


def test_boot_turns_carry_interruptible_flags(tmp_path):
    config = _boot_config(tmp_path)
    (config.agent_dir / "core" / "migrations" / "001-safe.md").write_text("---\ninterruptible: true\n---\n\nsafe")
    (config.agent_dir / "core" / "pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "9.9.9"\n')
    _record_snapshot(config, "9.9.9")

    turns = collect_boot_turns(
        state=_authed_state(),
        config=config,
        config_issues=["BAD=1 is invalid; reverted to default"],
        agent_message="You restarted after a routine shutdown.",
        first_start=False,
    )

    # Interruptible migration batch, then config issues and greeting, which stay non-interruptible.
    assert [turn.interruptible for turn in turns] == [True, False, False]
    assert all(turn.is_user is False and turn.file_paths == [] for turn in turns)


def test_restart_only_boot_is_just_the_greeting(tmp_path):
    """A plain restart has no converge turns: the greeting is the only turn, and it is the daemon
    restore point (it runs the restart skill), exactly as it is on every restart."""
    config = _boot_config(tmp_path)
    (config.agent_dir / "core" / "pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "9.9.9"\n')
    _record_snapshot(config, "9.9.9")
    state = _authed_state()

    with patch("core.loops.logger.startup") as startup_log:
        turns = collect_boot_turns(
            state=state,
            config=config,
            config_issues=[],
            agent_message="You restarted after a routine shutdown.",
            first_start=False,
        )

    assert len(turns) == 1
    assert turns[0].text.startswith("[System Restart]")
    startup_log.assert_called_once_with("Boot turn: restart greeting")


def test_first_start_pre_marks_migrations_and_greets_with_setup(tmp_path):
    config = _boot_config(tmp_path)
    (config.agent_dir / "core" / "migrations" / "001-x.md").write_text("x")  # pre-marked, not run
    (config.agent_dir / "core" / "migrations" / "002-before.md").write_text(f"{BEFORE_SYNC_FRONTMATTER}before")
    (config.agent_dir / "core" / "pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "9.9.9"\n')
    (config.core_prompts_dir / "birth.md").write_text("welcome, run setup")
    state = _authed_state()

    turns = collect_boot_turns(state=state, config=config, config_issues=[], agent_message="first start", first_start=True)

    assert len(turns) == 1
    assert "welcome, run setup" in turns[0].text
    assert state.persisted.applied_migrations == ["001-x", "002-before"]
    # Birth owns the initial attach, so no separate sync turn fires on first start.


def test_restart_greeting_carries_pending_boot_message(tmp_path):
    config = _boot_config(tmp_path)
    state = _authed_state()
    state.persisted.pending_boot_message = (
        "[Your context was just compacted; the summary is above.]\n\nnew day: greet warmly, summary at dreamer/x.md"
    )

    turns = collect_boot_turns(
        state=state,
        config=config,
        config_issues=[],
        agent_message="You restarted.",
        first_start=False,
    )

    assert len(turns) == 1
    assert "new day: greet warmly" in turns[0].text
    # The message is consumed so it isn't re-surfaced on the next boot.
    assert state.persisted.pending_boot_message is None


def test_pending_boot_message_consumed_even_on_unauthenticated_boot(tmp_path):
    """It must be consumed on the boot it was set for, never stranded to a later restart, even when
    the greeting is skipped because the provider is not authenticated."""
    from core.loops import greeting_turn

    config = _boot_config(tmp_path)
    state = vm.State()  # no provider_status -> unauthenticated
    state.persisted.pending_boot_message = "[Your context was just compacted; the summary is above.]\n\nnew day"

    result = greeting_turn(config=config, state=state, agent_message="You restarted.", first_start=False)

    assert result is None  # no greeting on an unauthenticated boot
    assert state.persisted.pending_boot_message is None  # but the one-shot message is still consumed
