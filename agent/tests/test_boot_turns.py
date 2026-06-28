"""Tests for boot-turn assembly: boot-time control-flow delivered as ordered, non-interruptible turns."""

import core.models as vm
from core.main import collect_boot_turns
from core.provider import ProviderAuthState, ProviderStatus


def _boot_config(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    for sub in ["core/migrations", "core/prompts", "skills", "data", "dreamer"]:
        (config.agent_dir / sub).mkdir(parents=True, exist_ok=True)
    return config


def _authed_state() -> vm.State:
    # The greeting is gated on an authenticated provider; these tests exercise the assembly, so authenticate.
    state = vm.State()
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")
    return state


def test_boot_turns_ordered_migrations_then_skill_then_config_then_greeting(tmp_path):
    config = _boot_config(tmp_path)
    (config.agent_dir / "core" / "migrations" / "001-x.md").write_text("do migration x")
    (config.agent_dir / "core" / "default-skills.txt").write_text("alpha\n")  # alpha missing on disk

    turns = collect_boot_turns(
        state=_authed_state(),
        config=config,
        config_issues=["BAD=1 is invalid; reverted to default"],
        greeting_reason="restart: clean restart",
        first_start=False,
    )

    assert len(turns) == 4
    assert "[Migration: 001-x]" in turns[0]
    assert "skills-install alpha" in turns[1]
    assert "BAD=1" in turns[2]
    assert "[System: restart: clean restart]" in turns[3]


def test_first_start_pre_marks_migrations_and_greets_with_setup(tmp_path):
    config = _boot_config(tmp_path)
    (config.agent_dir / "core" / "migrations" / "001-x.md").write_text("x")  # pre-marked, not run
    (config.core_prompts_dir / "first_start_setup.md").write_text("welcome, run setup")
    state = _authed_state()

    turns = collect_boot_turns(state=state, config=config, config_issues=[], greeting_reason="first_start", first_start=True)

    assert len(turns) == 1
    assert "welcome, run setup" in turns[0]
    assert state.persisted.applied_migrations == ["001-x"]


def test_restart_greeting_carries_pending_dreamer_summary(tmp_path):
    config = _boot_config(tmp_path)
    (config.dreamer_dir / "2026-06-27.md").write_text("today I learned the user likes tea")
    state = _authed_state()
    state.persisted.show_dreamer_summary = True

    turns = collect_boot_turns(state=state, config=config, config_issues=[], greeting_reason="nightly: dreamer ran", first_start=False)

    assert len(turns) == 1
    assert "Dreamer Summary" in turns[0]
    assert "likes tea" in turns[0]
    # The flag is consumed so the summary isn't re-surfaced on the next boot.
    assert state.persisted.show_dreamer_summary is False
