"""Tests for the default-skill reconciler and the recall skill's search query."""

import importlib.util
import pathlib

import pytest

import core.config as cfg
from core.default_skills import default_skill_sync_turn, missing_default_skills
from core.events import AssistantEvent, EventBus


@pytest.fixture
def skills_config(tmp_path):
    """A config whose agent_dir has core/ (the default-skills list) and skills/ (materialized skills)."""
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    (config.agent_dir / "skills").mkdir(parents=True)
    (config.agent_dir / "core").mkdir(parents=True)
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config


def _write_defaults(config, names):
    (config.agent_dir / "core" / "default-skills.txt").write_text("\n".join(names) + "\n")


def _install(config, name):
    skill_dir = config.agent_dir / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n")


def test_no_defaults_file_is_noop(skills_config):
    assert missing_default_skills(skills_config) == []
    assert default_skill_sync_turn(config=skills_config) is None


def test_all_installed_returns_nothing(skills_config):
    _write_defaults(skills_config, ["alpha", "beta"])
    _install(skills_config, "alpha")
    _install(skills_config, "beta")

    assert missing_default_skills(skills_config) == []
    assert default_skill_sync_turn(config=skills_config) is None


def test_missing_skills_return_one_boot_turn(skills_config):
    _write_defaults(skills_config, ["alpha", "beta", "gamma"])
    _install(skills_config, "beta")

    assert missing_default_skills(skills_config) == ["alpha", "gamma"]
    body = default_skill_sync_turn(config=skills_config)

    assert body is not None
    assert "skills-install alpha" in body
    assert "skills-install gamma" in body
    assert "skills-install beta" not in body
    assert "restart_vesta" in body


def test_first_start_is_noop_even_when_missing(skills_config):
    _write_defaults(skills_config, ["alpha"])

    assert default_skill_sync_turn(config=skills_config, first_start=True) is None


def test_rerun_returns_same_turn_each_boot(skills_config):
    _write_defaults(skills_config, ["alpha"])

    first = default_skill_sync_turn(config=skills_config)
    second = default_skill_sync_turn(config=skills_config)

    assert first is not None and first == second


# --- recall skill search query (mirrors EventBus.search over a real db) ---


def _load_recall():
    path = pathlib.Path(__file__).resolve().parent.parent / "skills" / "recall" / "cli" / "src" / "recall_cli" / "cli.py"
    spec = importlib.util.spec_from_file_location("recall", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recall_finds_events_written_by_eventbus(tmp_path):
    bus = EventBus(data_dir=tmp_path)
    bus.emit(AssistantEvent(type="assistant", text="what is the weather in paris"))
    bus.emit(AssistantEvent(type="assistant", text="it is sunny in paris today"))
    bus.emit(AssistantEvent(type="assistant", text="how about london"))
    bus.close()

    recall = _load_recall()
    db_path = tmp_path / "events.db"
    results = recall.search(db_path, "paris", limit=20)
    assert len(results) == 2
    assert all("paris" in r["content"] for r in results)

    assert recall.search(db_path, "nonexistent", limit=20) == []
    assert recall.format_results([]) == "No results found."


def test_recall_missing_db_returns_empty(tmp_path):
    recall = _load_recall()
    assert recall.search(tmp_path / "nope.db", "anything", limit=20) == []
