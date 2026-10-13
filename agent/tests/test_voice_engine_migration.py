"""The shell steps of the voice engine migration, run for real against a temporary workspace.

Step 2 of the migration saves a box's own voice work to a patch file and then makes the voice
skill equal to stock. It runs on every box, and a mistake in it loses an agent's work, so the
commands the migration tells the agent to run are the commands this test runs.
"""

import pathlib as pl
import re
import subprocess

import pytest

MIGRATION = pl.Path(__file__).parents[1] / "core/migrations/2026-10-voice-engine.md"
TAG = "agent-v9.9.9"
VOICE = "agent/skills/voice"
HANDLERS = f"{VOICE}/cli/src/voice/handlers.py"
OWN = f"{VOICE}/cli/src/voice/providers/own.py"


def _step_two_blocks() -> list[str]:
    """The bash blocks of step 2: the save-and-take block, then the sweep outside the skill."""
    step = MIGRATION.read_text().split("### 2.", 1)[1].split("### 3.", 1)[0]
    return re.findall(r"```bash\n(.*?)```", step, flags=re.DOTALL)


SAVE_AND_TAKE, SWEEP = _step_two_blocks()
# The first statement of the block alone: the run that stops right after the save.
SAVE_ONLY = SAVE_AND_TAKE.split("[ -f ~/.voice/stock-taken ]", 1)[0]


def _git(home: pl.Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=home, check=True, capture_output=True, text=True).stdout


def _bash(home: pl.Path, script: str) -> str:
    result = subprocess.run(
        ["bash", "-c", f"set -e\n{script}"],
        cwd=home,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null"},
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _write(home: pl.Path, path: str, text: str) -> None:
    target = home / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


@pytest.fixture
def home(tmp_path: pl.Path) -> pl.Path:
    """A workspace like a box's: `~` is the checkout, and only `agent/` minus `core/` is tracked."""
    home = tmp_path / "home"
    home.mkdir()
    _git(home, "init", "-q", "-b", "testbox")
    _git(home, "config", "user.name", "testbox")
    _git(home, "config", "user.email", "testbox@vesta")
    _git(home, "config", "commit.gpgsign", "false")
    _write(home, ".gitignore", "/*\n!/.gitignore\n!/agent/\n/agent/core/\n")
    # Each block reads the version of the engine and sets `$TAG` from it.
    _write(home, "agent/core/pyproject.toml", f'[project]\nversion = "{TAG.removeprefix("agent-v")}"\n')
    _write(home, HANDLERS, "stock handlers\n")
    _write(home, OWN, "STT = {}\n")
    _write(home, "agent/skills/whatsapp/SKILL.md", "calls use /tts/speak and /stt/listen\n")
    _write(home, "agent/MEMORY.md", "# memory\n")
    _git(home, "add", "-A")
    _git(home, "commit", "-q", "-m", "stock")
    _git(home, "tag", "--no-sign", TAG)
    return home


def _own_work(home: pl.Path) -> None:
    """A committed change to a stock file, and a file of the box's own that git does not track yet."""
    _write(home, HANDLERS, "stock handlers\nmy patch\n")
    _git(home, "commit", "-q", "-am", "mine")
    _write(home, f"{VOICE}/cli/src/voice/local_stt.py", "local whisper hack\n")


def _equal_to_stock(home: pl.Path) -> bool:
    return _git(home, "status", "--porcelain", "--", VOICE) == "" and _git(home, "diff", TAG, "--", VOICE) == ""


def _patch(home: pl.Path) -> str:
    return (home / ".voice/own-work.patch").read_text()


def test_each_local_line_and_file_is_saved_and_the_skill_is_then_equal_to_stock(home: pl.Path) -> None:
    _own_work(home)

    _bash(home, SAVE_AND_TAKE)

    assert "+my patch" in _patch(home)
    assert "+local whisper hack" in _patch(home)
    assert _equal_to_stock(home)
    assert not (home / f"{VOICE}/cli/src/voice/local_stt.py").exists()
    assert (home / HANDLERS).read_text() == "stock handlers\n"


def test_a_second_run_changes_nothing(home: pl.Path) -> None:
    _own_work(home)
    _bash(home, SAVE_AND_TAKE)
    patch, head = _patch(home), _git(home, "rev-parse", "HEAD")

    _bash(home, SAVE_AND_TAKE)

    assert _patch(home) == patch
    assert _git(home, "rev-parse", "HEAD") == head
    assert _equal_to_stock(home)


def test_a_run_after_a_rebuild_keeps_the_rebuilt_work(home: pl.Path) -> None:
    _own_work(home)
    _bash(home, SAVE_AND_TAKE)
    patch = _patch(home)
    _write(home, OWN, 'STT = {"whisper-local": 1}\n')
    _write(home, f"{VOICE}/cli/src/voice/providers/whisper_local.py", "the adapter\n")

    _bash(home, SAVE_AND_TAKE)

    assert (home / OWN).read_text() == 'STT = {"whisper-local": 1}\n'
    assert (home / f"{VOICE}/cli/src/voice/providers/whisper_local.py").read_text() == "the adapter\n"
    assert _patch(home) == patch


def test_a_run_that_stopped_after_the_save_ends_equal_to_stock_with_the_same_patch(home: pl.Path) -> None:
    _own_work(home)
    _bash(home, SAVE_ONLY)
    patch = _patch(home)
    assert not _equal_to_stock(home)

    _bash(home, SAVE_AND_TAKE)

    assert _patch(home) == patch
    assert _equal_to_stock(home)


def test_a_run_that_stopped_in_the_middle_of_the_restore_ends_equal_to_stock_with_the_same_patch(home: pl.Path) -> None:
    _own_work(home)
    _bash(home, SAVE_ONLY)
    patch = _patch(home)
    _git(home, "restore", f"--source={TAG}", "--staged", "--worktree", "--", VOICE)

    _bash(home, SAVE_AND_TAKE)

    assert _patch(home) == patch
    assert "+my patch" in patch
    assert _equal_to_stock(home)


def test_a_box_with_no_local_change_gets_an_empty_patch_and_no_commit(home: pl.Path) -> None:
    head = _git(home, "rev-parse", "HEAD")

    _bash(home, SAVE_AND_TAKE)

    assert _patch(home) == ""
    assert _git(home, "rev-parse", "HEAD") == head
    assert (home / ".voice/stock-taken").exists()


def test_the_sweep_lists_a_file_of_the_box_that_names_a_voice_route_and_no_stock_file(home: pl.Path) -> None:
    _write(home, "agent/skills/voice-home/front end.py", 'ws.connect("/stt/listen")\n')
    _write(home, "agent/MEMORY.md", "# memory\nI read ~/.voice/voice_config.json for the voice id\n")
    _write(home, "agent/skills/notes/SKILL.md", "nothing about speech\n")

    found = _bash(home, SWEEP)

    assert "agent/skills/voice-home/front end.py:1:" in found
    assert "agent/MEMORY.md:2:" in found
    assert "whatsapp" not in found
    assert "notes" not in found


def _interrupt_check() -> str:
    """The bash block of step 4, which says if the user's choice about interruptions must move."""
    step = MIGRATION.read_text().split("### 4.", 1)[1].split("### 5.", 1)[0]
    (block,) = re.findall(r"```bash\n(.*?)```", step, flags=re.DOTALL)
    return block


@pytest.mark.parametrize(
    ("config", "answer"),
    [
        ('{"stt": {"provider": "deepgram", "interrupt_tts": false}, "behavior": null}', "move"),
        ('{"stt": {"provider": "deepgram", "interrupt_tts": false}, "behavior": {"barge_in": true}}', "nothing-to-move"),
        ('{"stt": {"provider": "deepgram", "interrupt_tts": true}}', "nothing-to-move"),
        ('{"stt": null, "tts": null}', "nothing-to-move"),
        ("{not json", "nothing-to-move"),
    ],
)
def test_the_interrupt_check_says_move_only_for_a_choice_that_no_behavior_holds_yet(tmp_path: pl.Path, config: str, answer: str) -> None:
    _write(tmp_path, ".voice/voice_config.json", config)

    assert _bash(tmp_path, _interrupt_check()).strip() == answer


def test_the_interrupt_check_has_nothing_to_move_on_a_box_with_no_voice_config(tmp_path: pl.Path) -> None:
    assert _bash(tmp_path, _interrupt_check()).strip() == "nothing-to-move"


def test_the_migration_is_interruptible_and_marks_itself_by_its_file_name() -> None:
    text = MIGRATION.read_text()

    assert text.startswith("---\ninterruptible: true\n---\n")
    assert f'name="{MIGRATION.stem}"' in text
