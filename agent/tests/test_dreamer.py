"""Tests for nightly dreamer/memory scheduling."""

import datetime as dt
import json
from unittest.mock import patch

import core.models as vm


def _setup(tmp_path, *, dreamer_hour=4):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent", nightly_memory_hour=dreamer_hour)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    return config


def test_drops_dream_notification(tmp_path):
    from core.loops import process_nightly_memory

    config = _setup(tmp_path)
    state = vm.State()
    fake_now = dt.datetime(2025, 6, 15, config.nightly_memory_hour, 0, 0)

    with (
        patch("core.loops._now", return_value=fake_now),
        patch("core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        process_nightly_memory(state=state, config=config)

    files = list(config.notifications_dir.glob("nightly_dream-*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text())
    assert payload["source"] == "core"
    assert payload["type"] == "nightly_dream"
    assert payload["body"] == "dreamer prompt"
    # Persisted last_dreamer_run is unchanged until the agent itself calls mark_dreamer_complete.
    assert state.persisted.last_dreamer_run is None


def test_skips_when_already_run_today(tmp_path):
    from core.loops import process_nightly_memory

    config = _setup(tmp_path)
    fake_now = dt.datetime(2025, 6, 15, config.nightly_memory_hour, 0, 0)

    state = vm.State()
    state.persisted.last_dreamer_run = fake_now

    with (
        patch("core.loops._now", return_value=fake_now),
        patch("core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        process_nightly_memory(state=state, config=config)

    assert list(config.notifications_dir.glob("nightly_dream-*.json")) == []


def test_skips_before_dreamer_hour(tmp_path):
    from core.loops import process_nightly_memory

    config = _setup(tmp_path, dreamer_hour=4)
    state = vm.State()
    earlier = dt.datetime(2025, 6, 15, 2, 0, 0)

    with (
        patch("core.loops._now", return_value=earlier),
        patch("core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        process_nightly_memory(state=state, config=config)

    assert list(config.notifications_dir.glob("nightly_dream-*.json")) == []


def test_retries_after_dream_hour_when_not_done_today(tmp_path):
    """If the dream didn't complete (rate limit, crash) and the prior notification is gone, fire again — even past the configured hour."""
    from core.loops import process_nightly_memory

    config = _setup(tmp_path, dreamer_hour=4)
    state = vm.State()
    state.persisted.last_dreamer_run = dt.datetime(2025, 6, 14, 4, 0, 0)  # yesterday
    later_today = dt.datetime(2025, 6, 15, 7, 30, 0)

    with (
        patch("core.loops._now", return_value=later_today),
        patch("core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        process_nightly_memory(state=state, config=config)

    assert len(list(config.notifications_dir.glob("nightly_dream-*.json"))) == 1


def test_drop_does_not_persist_last_dreamer_run(tmp_path):
    """Dropping the notification must not advance persisted.last_dreamer_run — only the agent's mark_dreamer_complete call does that.

    Protects against a regression where last_dreamer_run was committed at drop time, which locked the
    dreamer out for the day even if it never actually ran.
    """
    from core.loops import process_nightly_memory

    config = _setup(tmp_path)
    state = vm.State()
    fake_now = dt.datetime(2025, 6, 15, config.nightly_memory_hour, 0, 0)

    with (
        patch("core.loops._now", return_value=fake_now),
        patch("core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        process_nightly_memory(state=state, config=config)

    assert state.persisted.last_dreamer_run is None
