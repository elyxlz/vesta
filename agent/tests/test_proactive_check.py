"""Tests for the proactive check's and the dream's prompts: the base prompt plus one read nudge per
skill file edited since the previous run, decided from file mtimes alone."""

import datetime as dt
import json
import os
from unittest.mock import patch

import pytest

import core.config as cfg
import core.models as vm
from core.loops import check_proactive_task, process_nightly_memory

T0 = dt.datetime(2025, 6, 15, 12, 0, 0)
BEFORE = T0 - dt.timedelta(hours=1)
AFTER = T0 + dt.timedelta(minutes=5)
BASE = "Time for a proactive check."
FOCUS_NUDGE = "Read `~/agent/skills/proactive-check/focus.md`, it has changed since last time."
SKILL_NUDGE = "Read `~/agent/skills/proactive-check/SKILL.md`, it has changed since last time."
DREAM_NUDGE = "Read `~/agent/skills/dream/SKILL.md`, it has changed since last time."


def _write_at(path, edited_at):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("routine")
    os.utime(path, (edited_at.timestamp(), edited_at.timestamp()))


def _config(tmp_path):
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent", nightly_memory_hour=4)
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config


def _dropped_body(config, stem):
    files = list(config.notifications_dir.glob(f"{stem}-*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text())["body"]


@pytest.mark.parametrize(
    "focus_at,skill_at,since,expected",
    [
        (BEFORE, BEFORE, T0, BASE),
        (AFTER, BEFORE, T0, f"{BASE} {FOCUS_NUDGE}"),
        (BEFORE, AFTER, T0, f"{BASE} {SKILL_NUDGE}"),
        (AFTER, AFTER, T0, f"{BASE} {FOCUS_NUDGE} {SKILL_NUDGE}"),
        (BEFORE, BEFORE, None, f"{BASE} {FOCUS_NUDGE}"),
    ],
    ids=["unchanged", "focus-edited", "skill-edited", "both-edited", "first-check-after-boot"],
)
def test_check_nudges_a_read_of_each_skill_file_edited_since_the_previous_check(tmp_path, focus_at, skill_at, since, expected):
    config = _config(tmp_path)
    _write_at(config.skills_dir / "proactive-check" / "focus.md", focus_at)
    _write_at(config.skills_dir / "proactive-check" / "SKILL.md", skill_at)

    with patch("core.loops.load_prompt", return_value=BASE):
        check_proactive_task(config=config, since=since)

    assert _dropped_body(config, "proactive_check") == expected


def test_check_without_the_skill_files_is_the_base_alone(tmp_path):
    """A box whose sync has not delivered the files yet gets no nudge to read what is not there."""
    config = _config(tmp_path)

    with patch("core.loops.load_prompt", return_value=BASE):
        check_proactive_task(config=config, since=None)

    assert _dropped_body(config, "proactive_check") == BASE


@pytest.mark.parametrize(
    "skill_at,last_dreamer_run,expected",
    [
        (dt.datetime(2025, 6, 13, 12, 0, 0), dt.datetime(2025, 6, 14, 4, 0, 0), "dreamer prompt"),
        (dt.datetime(2025, 6, 14, 12, 0, 0), dt.datetime(2025, 6, 14, 4, 0, 0), f"dreamer prompt {DREAM_NUDGE}"),
        (dt.datetime(2025, 6, 13, 12, 0, 0), None, f"dreamer prompt {DREAM_NUDGE}"),
    ],
    ids=["unchanged-since-last-dream", "edited-since-last-dream", "never-dreamed"],
)
def test_dream_nudges_a_read_of_its_skill_when_edited_since_the_last_dream(tmp_path, skill_at, last_dreamer_run, expected):
    config = _config(tmp_path)
    _write_at(config.skills_dir / "dream" / "SKILL.md", skill_at)
    state = vm.State()
    state.persisted.first_start_done = True
    state.persisted.last_dreamer_run = last_dreamer_run
    # Minute 59 is at or past every possible jitter instant inside the dreamer hour.
    now = dt.datetime(2025, 6, 15, 4, 59, 0)

    with (
        patch("core.loops._now", return_value=now),
        patch("core.loops.load_prompt", return_value="dreamer prompt\n"),
    ):
        process_nightly_memory(state=state, config=config)

    assert _dropped_body(config, "nightly_dream") == expected
