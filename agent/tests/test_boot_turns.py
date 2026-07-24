"""Tests for boot-turn assembly: boot-time control-flow delivered as ordered, non-interruptible turns."""

import subprocess

import core.config as cfg
import core.models as vm
from core.main import BOOT_RESTORE_ORIENTATION, collect_boot_turns
from core.provider import ProviderAuthState, ProviderStatus


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


def _record_snapshot(config, version):
    home = config.agent_dir.parent
    subprocess.run(["git", "init", "-q", "-b", "agent"], cwd=home, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@vesta", "commit", "-q", "--allow-empty", "-m", "stock"],
        cwd=home,
        check=True,
    )
    subprocess.run(["git", "tag", f"agent-v{version}"], cwd=home, check=True)


def test_boot_turns_ordered_migrations_then_sync_then_config_then_greeting(tmp_path):
    config = _boot_config(tmp_path)
    (config.agent_dir / "core" / "migrations" / "001-x.md").write_text("do migration x")
    (config.agent_dir / "core" / "migrations" / "002-y.md").write_text("do migration y")
    # The running version's snapshot is absent from Git, so the upstream-sync turn fires.
    (config.agent_dir / "core" / "pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "9.9.9"\n')

    turns = collect_boot_turns(
        state=_authed_state(),
        config=config,
        config_issues=["BAD=1 is invalid; reverted to default"],
        greeting_reason="clean: routine restart, no specific reason",
        first_start=False,
    )

    assert len(turns) == 4
    # The first converge turn carries the daemon-restore orientation so a migration/upgrade boot
    # restores daemons via the restart skill first, exactly as a plain restart would.
    assert turns[0].startswith(BOOT_RESTORE_ORIENTATION)
    assert "[Migration: 001-x]" in turns[0]
    assert "[Migration: 002-y]" in turns[0]
    assert "[Upstream sync]" in turns[1]
    assert "BAD=1" in turns[2]
    assert "[System Restart]\nReason: routine restart, no specific reason" in turns[3]
    # The orientation rides only the first converge turn, never the restart greeting (it already
    # runs the restart skill) or the later converge turns.
    assert BOOT_RESTORE_ORIENTATION not in turns[1]
    assert BOOT_RESTORE_ORIENTATION not in turns[3]


def test_restart_only_boot_carries_no_daemon_orientation(tmp_path):
    """A plain restart has no converge turns: the greeting is the restart turn itself, so it must not
    be prefixed with the converge-turn daemon-restore orientation."""
    config = _boot_config(tmp_path)
    (config.agent_dir / "core" / "pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "9.9.9"\n')
    _record_snapshot(config, "9.9.9")
    state = _authed_state()

    turns = collect_boot_turns(state=state, config=config, config_issues=[], greeting_reason="clean: routine restart", first_start=False)

    assert len(turns) == 1
    assert BOOT_RESTORE_ORIENTATION not in turns[0]


def test_first_start_pre_marks_migrations_and_greets_with_setup(tmp_path):
    config = _boot_config(tmp_path)
    (config.agent_dir / "core" / "migrations" / "001-x.md").write_text("x")  # pre-marked, not run
    (config.agent_dir / "core" / "pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "9.9.9"\n')
    (config.core_prompts_dir / "birth.md").write_text("welcome, run setup")
    state = _authed_state()

    turns = collect_boot_turns(state=state, config=config, config_issues=[], greeting_reason="first_start", first_start=True)

    assert len(turns) == 1
    assert "welcome, run setup" in turns[0]
    assert state.persisted.applied_migrations == ["001-x"]
    # Birth owns the initial attach, so no separate sync turn fires on first start.


def test_restart_greeting_carries_pending_boot_message(tmp_path):
    config = _boot_config(tmp_path)
    state = _authed_state()
    state.persisted.pending_boot_message = (
        "[Your context was just compacted; the summary is above.]\n\nnew day: greet warmly, summary at dreamer/x.md"
    )

    turns = collect_boot_turns(state=state, config=config, config_issues=[], greeting_reason="clean: restarted", first_start=False)

    assert len(turns) == 1
    assert "new day: greet warmly" in turns[0]
    # The message is consumed so it isn't re-surfaced on the next boot.
    assert state.persisted.pending_boot_message is None


def test_pending_boot_message_consumed_even_on_unauthenticated_boot(tmp_path):
    """It must be consumed on the boot it was set for, never stranded to a later restart, even when
    the greeting is skipped because the provider is not authenticated."""
    from core.loops import greeting_turn

    config = _boot_config(tmp_path)
    state = vm.State()  # no provider_status -> unauthenticated
    state.persisted.pending_boot_message = "[Your context was just compacted; the summary is above.]\n\nnew day"

    result = greeting_turn(config=config, state=state, reason="clean: restarted")

    assert result is None  # no greeting on an unauthenticated boot
    assert state.persisted.pending_boot_message is None  # but the one-shot message is still consumed
