"""Tests for wiring a skill's declared hooks into `~/.claude/settings.json`.

A skill that ships a PreToolUse guard used to ship a paragraph asking each agent to hand-edit
settings.json, and `reconcile_claude_runtime` writes that file only when it is ABSENT. So on every
existing box the guard stayed inert while the skill read as installed: the exact silent-no-op shape
those guards exist to catch, one layer up.

Each test here therefore checks an effect rather than a return value, and the last one checks that
the merge is actually CALLED, because a merge nothing invokes is the same failure again.
"""

import inspect
import json
import pathlib as pl

import core.claude_runtime as rt

DECLARATION = {"PreToolUse": [{"matcher": "Bash", "script": "scripts/guard.py"}]}


def make_skill(root: pl.Path, name: str = "dream", declaration: object = DECLARATION, script: bool = True) -> pl.Path:
    skill = root / name
    (skill / "scripts").mkdir(parents=True, exist_ok=True)
    if script:
        (skill / "scripts" / "guard.py").write_text("import sys\nsys.exit(0)\n")
    if declaration is not None:
        (skill / "hooks.json").write_text(json.dumps(declaration))
    return skill


def commands(settings: pl.Path, event: str = "PreToolUse") -> list[str]:
    hooks = json.loads(settings.read_text()).get("hooks", {}).get(event, [])
    return [hook["command"] for group in hooks for hook in group["hooks"]]


def test_a_declared_guard_reaches_a_settings_file_that_never_mentioned_it(tmp_path):
    skill = make_skill(tmp_path)
    settings = tmp_path / "settings.json"
    settings.write_text('{"permissions":{"allow":[]}}')

    rt._merge_skill_hooks(settings, [skill])

    assert commands(settings) == [f"python3 {skill}/scripts/guard.py"]
    assert json.loads(settings.read_text())["permissions"] == {"allow": []}


def test_merging_twice_wires_the_guard_once(tmp_path):
    skill = make_skill(tmp_path)
    settings = tmp_path / "settings.json"
    settings.write_text("{}")

    rt._merge_skill_hooks(settings, [skill])
    first = settings.read_text()
    rt._merge_skill_hooks(settings, [skill])

    assert settings.read_text() == first
    assert len(commands(settings)) == 1


def test_a_hand_written_hook_survives_the_merge(tmp_path):
    skill = make_skill(tmp_path)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 mine.py"}]}]}}))

    rt._merge_skill_hooks(settings, [skill])

    assert "python3 mine.py" in commands(settings)
    assert len(commands(settings)) == 2


def test_a_declaration_naming_a_script_that_is_not_on_disk_wires_nothing(tmp_path):
    """The worst outcome is a hook whose command does not exist: it fails silently and reads clean."""
    skill = make_skill(tmp_path, script=False)
    settings = tmp_path / "settings.json"
    settings.write_text("{}")

    rt._merge_skill_hooks(settings, [skill])

    assert settings.read_text() == "{}"


def test_a_malformed_declaration_leaves_settings_untouched(tmp_path):
    skill = make_skill(tmp_path, declaration=None)
    (skill / "hooks.json").write_text("{not json")
    settings = tmp_path / "settings.json"
    settings.write_text("{}")

    rt._merge_skill_hooks(settings, [skill])

    assert settings.read_text() == "{}"


def test_unreadable_settings_are_left_alone_rather_than_rewritten(tmp_path):
    skill = make_skill(tmp_path)
    settings = tmp_path / "settings.json"
    settings.write_text("{ broken")

    rt._merge_skill_hooks(settings, [skill])

    assert settings.read_text() == "{ broken"


def test_the_dream_skill_declares_only_scripts_that_exist(tmp_path):
    """A control on the shipped declaration itself, which is the thing that rots quietly."""
    skill = pl.Path(__file__).resolve().parents[1] / "skills" / "dream"
    declared = rt._declared_hooks(skill)

    assert declared["PreToolUse"], "the dream skill declares no hooks at all"
    assert len(declared["PreToolUse"]) == len(json.loads((skill / "hooks.json").read_text())["PreToolUse"])


def test_reconcile_actually_calls_the_merge(tmp_path):
    """The finding this whole change answers was that nothing invoked the wiring."""
    assert "_merge_skill_hooks(" in inspect.getsource(rt.reconcile_claude_runtime)
