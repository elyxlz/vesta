"""Tests for the dream skill's PreToolUse guards and for the script that verifies them.

Every guard here fails open, so "it did not crash" is not evidence that it is working. Each one is
therefore checked in BOTH directions: it must deny the input it exists for, and it must wave
ordinary work through. The verify_hooks tests go one step further and gut a wired guard on purpose,
because a checker that cannot tell a real guard from a `sys.exit(0)` stub is the failure it exists
to prevent.
"""

import importlib.util
import json
import pathlib as pl
import subprocess
import sys

import pytest

SCRIPTS = pl.Path(__file__).resolve().parents[1] / "skills" / "dream" / "scripts"
TMP_REF_GUARD = SCRIPTS / "tmp_ref_guard.py"
BLIND_MUTATION_GUARD = SCRIPTS / "blind_mutation_guard.py"
VERIFY_HOOKS = SCRIPTS / "verify_hooks.py"


def load(script: pl.Path):
    spec = importlib.util.spec_from_file_location(script.stem, script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_hook(script: pl.Path, payload: dict, home: pl.Path) -> tuple[int, str]:
    """Call a guard exactly as Claude Code does: the payload on stdin, the verdict on stdout."""
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
    )
    return proc.returncode, proc.stdout


def hook_decision(stdout: str) -> str | None:
    for line in reversed(stdout.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)["hookSpecificOutput"]["permissionDecision"]
    return None


def test_tmp_ref_guard_self_test_is_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert load(TMP_REF_GUARD).self_test() == []


def test_tmp_ref_guard_denies_a_tmp_path_written_into_task_metadata(tmp_path):
    note = tmp_path / ".tasks" / "metadata" / "abcd1234.md"
    note.parent.mkdir(parents=True)
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(note), "content": "package saved at /tmp/claim/receipt.pdf"}}
    code, out = run_hook(TMP_REF_GUARD, payload, tmp_path)
    assert code == 0  # a deny is still a successful hook run
    assert hook_decision(out) == "deny"
    assert "/tmp/claim/receipt.pdf" in out


@pytest.mark.parametrize(
    ("label", "tool_input"),
    [
        ("a durable path", {"file_path": "{note}", "content": "package at ~/agent/data/claim/receipt.pdf"}),
        ("prose recording that the path is dead", {"file_path": "{note}", "content": "/tmp/claim no longer exists, recovered"}),
        ("scratch work outside task metadata", {"file_path": "/tmp/scratch.md", "content": "notes at /tmp/claim/receipt.pdf"}),
    ],
)
def test_tmp_ref_guard_allows_ordinary_writes(tmp_path, label, tool_input):
    note = tmp_path / ".tasks" / "metadata" / "abcd1234.md"
    note.parent.mkdir(parents=True)
    resolved = {k: v.replace("{note}", str(note)) for k, v in tool_input.items()}
    code, out = run_hook(TMP_REF_GUARD, {"tool_name": "Write", "tool_input": resolved}, tmp_path)
    assert (code, out.strip()) == (0, ""), label


def test_blind_mutation_guard_self_test_is_clean():
    proc = subprocess.run([sys.executable, str(BLIND_MUTATION_GUARD), "--self-test"], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout


def test_blind_mutation_guard_denies_an_id_scraped_by_default_awk_splitting(tmp_path):
    command = "tasks remind delete $(tasks remind list --task X | grep -i WATCH | awk '{print $2}')"
    code, out = run_hook(BLIND_MUTATION_GUARD, {"tool_name": "Bash", "tool_input": {"command": command}}, tmp_path)
    assert code == 0
    assert hook_decision(out) == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "tasks remind delete $(tasks remind list --json | python3 -c 'import sys; print(1)')",
        "tasks remind delete $(tasks remind list | grep W | awk -F'\\t' '{print $2}')",
        "tasks remind delete a9fa757e",
        "tasks remind list | grep W | awk '{print $2}'",
    ],
)
def test_blind_mutation_guard_allows_every_correct_form(tmp_path, command):
    code, out = run_hook(BLIND_MUTATION_GUARD, {"tool_name": "Bash", "tool_input": {"command": command}}, tmp_path)
    assert (code, out.strip()) == (0, "")


def write_settings(home: pl.Path, *commands: str) -> None:
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    hooks = [{"matcher": "*", "hooks": [{"type": "command", "command": command}]} for command in commands]
    settings.write_text(json.dumps({"hooks": {"PreToolUse": hooks}}))


def run_verify_hooks(home: pl.Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VERIFY_HOOKS)],
        capture_output=True,
        text=True,
        check=False,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
    )


def test_verify_hooks_passes_a_guard_that_still_bites(tmp_path):
    write_settings(tmp_path, f"{sys.executable} {TMP_REF_GUARD}", f"{sys.executable} {BLIND_MUTATION_GUARD}")
    proc = run_verify_hooks(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "2 wired, 0 broken, 0 not fully exercised" in proc.stdout


def test_verify_hooks_catches_a_guard_gutted_to_exit_zero(tmp_path):
    """The whole point: a toothless guard parses, runs, and allows everything, exactly like a
    healthy one, and only its known-bad input tells them apart."""
    stub = tmp_path / "tmp_ref_guard.py"
    stub.write_text("import sys\n\nsys.exit(0)\n")
    write_settings(tmp_path, f"{sys.executable} {stub}")
    proc = run_verify_hooks(tmp_path)
    assert proc.returncode == 1
    assert "1 broken" in proc.stdout
    assert "Present but toothless" in proc.stdout


def test_verify_hooks_reports_a_wired_script_that_is_gone(tmp_path):
    write_settings(tmp_path, f"{sys.executable} {tmp_path / 'deleted_guard.py'}")
    proc = run_verify_hooks(tmp_path)
    assert proc.returncode == 1
    assert "MISSING ON DISK" in proc.stdout


def test_verify_hooks_names_a_guard_with_no_known_bad_input_instead_of_passing_it(tmp_path):
    unknown = tmp_path / "some_new_guard.py"
    unknown.write_text("import sys\n\nsys.exit(0)\n")
    write_settings(tmp_path, f"{sys.executable} {unknown}")
    proc = run_verify_hooks(tmp_path)
    assert proc.returncode == 0  # not broken, but not verified either
    assert "1 not fully exercised" in proc.stdout
    assert "some_new_guard.py: no known-bad input defined" in proc.stdout


def test_verify_hooks_does_not_count_a_wrapper_command_as_checked(tmp_path):
    write_settings(tmp_path, "bash -lc 'echo hi'")
    proc = run_verify_hooks(tmp_path)
    assert proc.returncode == 0
    assert "1 not fully exercised" in proc.stdout
    assert "not a bare .py command" in proc.stdout


def test_verify_hooks_separates_a_missing_settings_file_from_a_box_with_no_hooks(tmp_path):
    absent = run_verify_hooks(tmp_path)
    assert (absent.returncode, absent.stdout) == (2, "")
    assert "no settings file" in absent.stderr

    write_settings(tmp_path)
    empty = run_verify_hooks(tmp_path)
    assert empty.returncode == 0
    assert "no hooks wired" in empty.stdout


@pytest.mark.parametrize(
    ("label", "command"),
    [
        ("ps aux columns are space-padded and kill fails loudly", "kill $(ps aux | grep -i vesta | awk '{print $2}')"),
        ("the docker twin", "docker stop $(docker ps | grep vesta | awk '{print $1}')"),
    ],
)
def test_blind_mutation_guard_allows_another_tool_s_whitespace_safe_table(tmp_path, label, command):
    """Found in review: both of these were DENIED until 14 Aug 2026, and neither should be.

    The guard exists for a mutation that silently no-ops at exit 0 because a field boundary moved.
    `ps` and `docker ps` pad their columns and keep free text out of the fields before the id, and
    a wrong pid or container id fails loudly, so neither leg is present. The scrape source is now
    matched against the agent's own table-printing CLIs, a closed set, rather than every command.
    """
    code, out = run_hook(BLIND_MUTATION_GUARD, {"tool_name": "Bash", "tool_input": {"command": command}}, tmp_path)
    assert (code, out.strip()) == (0, ""), label
