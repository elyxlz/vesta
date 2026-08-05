"""Tests for the dream skill's memory_ledger script: durable-line extraction + lost vs reworded."""

import datetime as dt
import importlib.util
import pathlib as pl
import subprocess

import pytest

SCRIPT = pl.Path(__file__).resolve().parents[1] / "skills" / "dream" / "scripts" / "memory_ledger.py"

spec = importlib.util.spec_from_file_location("memory_ledger", SCRIPT)
assert spec is not None and spec.loader is not None
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)

RULE = "- WHEN a probe's success is itself the damage -> there is no safe way to run it live."
OTHER = "- WHEN a number moves and I reach for a cause -> check the number is even measuring me."


def _run_git(repo: pl.Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return done.stdout


@pytest.fixture
def memory(tmp_path, monkeypatch):
    """A throwaway git checkout holding agent/MEMORY.md (the box layout), the ledger pointed at it.
    Signing is disabled locally so host git config can never interfere."""
    (tmp_path / "agent").mkdir()
    mem = tmp_path / "agent" / "MEMORY.md"
    _run_git(tmp_path, "init", "-q")
    for key, value in (("user.name", "test"), ("user.email", "test@example.com"), ("commit.gpgsign", "false"), ("tag.gpgsign", "false")):
        _run_git(tmp_path, "config", key, value)
    mem.write_text("# MEMORY\n")
    _run_git(tmp_path, "add", "-A")
    _run_git(tmp_path, "commit", "-q", "-m", "birth")
    monkeypatch.setattr(ledger, "REPO", tmp_path)
    monkeypatch.setattr(ledger, "MEMORY", mem)
    return mem


def test_durable_lines_skips_the_user_state_section():
    text = "## 4. PROFILE\n### User State\n**Focus**: something that changes nightly\n"

    assert ledger.durable_lines(text) == ["## 4. PROFILE"]


def test_durable_lines_resumes_at_a_heading_of_any_level():
    """A heading at any level ends the User State window, so later sections stay watched."""
    text = f"### User State\n**Focus**: churn\n## 5. LEARNED PATTERNS\n{RULE}\n"

    assert ledger.durable_lines(text) == ["## 5. LEARNED PATTERNS", RULE]


def test_durable_lines_skips_the_self_state_paragraph_up_to_its_blank_line():
    """The template's Self section writes `**State**: ...`; the paragraph ends at the first blank
    line, so the filter can never swallow the rest of the file."""
    text = f"### Self (who vesta is becoming)\n**State**: how today felt\nstill the same paragraph\n\n{RULE}\n"

    assert ledger.durable_lines(text) == ["### Self (who vesta is becoming)", RULE]


def test_durable_lines_tolerates_a_dated_state_line():
    text = f"### Self\n**State (5 Aug)**: how today felt\n\n{RULE}\n"

    assert ledger.durable_lines(text) == ["### Self", RULE]


def test_durable_lines_state_paragraph_ends_at_a_heading():
    text = f"### Self\n**State**: the charge carried out of today\n## 5. LEARNED PATTERNS\n{RULE}\n"

    assert ledger.durable_lines(text) == ["### Self", "## 5. LEARNED PATTERNS", RULE]


def test_durable_lines_keeps_a_non_state_bold_field():
    # Only the State line is volatile; other `**Field**:` lines in durable sections are watched.
    text = "### Personal Details\n**Push level**: firm\n"

    assert ledger.durable_lines(text) == ["### Personal Details", "**Push level**: firm"]


def test_a_removed_rule_is_reported_lost():
    before, after = [RULE, OTHER], [OTHER]

    rewritten, lost = ledger.classify(before, after)

    assert lost == [RULE]
    assert rewritten == []


def test_a_removed_rule_is_still_lost_when_something_unrelated_arrives():
    after = [OTHER, "- Their birthday is in March and they hate being sung to."]

    rewritten, lost = ledger.classify([RULE, OTHER], after)

    assert lost == [RULE]
    assert rewritten == []


def test_a_reworded_rule_is_not_reported_lost():
    """Curation is mostly rewording, so a raw line diff floods the report it exists to make readable."""
    reworded = RULE.replace("no safe way", "no defensible way")

    rewritten, lost = ledger.classify([RULE, OTHER], [reworded, OTHER])

    assert lost == []
    assert rewritten == [(RULE, reworded)]


def test_two_rules_consolidated_into_one_line_are_not_reported_lost():
    merged = (
        "- WHEN a probe's success is itself the damage, or a number moves and I reach for a cause"
        " -> there is no safe way to run it live, and check the number is even measuring me."
    )

    rewritten, lost = ledger.classify([RULE, OTHER], [merged])

    assert lost == []
    assert [line for line, _ in rewritten] == [RULE, OTHER]


def test_an_unchanged_file_reports_nothing():
    assert ledger.classify([RULE, OTHER], [RULE, OTHER]) == ([], [])


def test_reordered_lines_report_nothing():
    """Curation reorders every night, and a positional diff would pair each moved line with itself."""
    assert ledger.classify([RULE, OTHER], [OTHER, RULE]) == ([], [])


def test_report_names_the_lost_rule_and_not_the_reworded_one(memory, capsys):
    memory.write_text(f"## RULES\n{RULE}\n{OTHER}\n")
    assert ledger.snapshot("Wrote two rules.") == 0
    memory.write_text(f"## RULES\n{RULE.replace('no safe way', 'no defensible way')}\n")

    ledger.report()

    out = capsys.readouterr().out
    assert "1 durable line(s) lost, 1 reworded" in out
    assert "no defensible way" in out
    assert OTHER in out


def test_report_is_clean_when_only_the_volatile_sections_changed(memory, capsys):
    memory.write_text(f"## RULES\n{RULE}\n### User State\n**Focus**: yesterday's read\n")
    assert ledger.snapshot("Refreshed the state.") == 0
    memory.write_text(f"## RULES\n{RULE}\n### User State\n**Focus**: a completely different read\n")

    ledger.report()

    assert "0 durable line(s) lost, 0 reworded" in capsys.readouterr().out


def test_report_says_so_when_there_is_no_baseline_yet(memory, capsys):
    """The first run on a new agent: commits exist but none carries the checkpoint prefix."""
    memory.write_text(f"## RULES\n{RULE}\n")

    assert ledger.report() == 0

    assert "no checkpoint commit" in capsys.readouterr().out


def test_a_checkpoint_commit_never_moves_the_baseline(memory, capsys):
    """The report keys on the dream subject prefix, not HEAD: a `git add -A && git commit -m
    checkpoint` between dreams (the upstream-sync flow) must not hide a loss it happened to commit."""
    memory.write_text(f"## RULES\n{RULE}\n{OTHER}\n")
    assert ledger.snapshot("Wrote two rules.") == 0
    memory.write_text(f"## RULES\n{OTHER}\n")
    _run_git(memory.parents[1], "add", "-A")
    _run_git(memory.parents[1], "commit", "-q", "-m", "checkpoint")

    ledger.report()

    out = capsys.readouterr().out
    assert "1 durable line(s) lost" in out
    assert RULE in out


def test_snapshot_commit_carries_the_date_and_the_summary(memory):
    repo = memory.parents[1]
    memory.write_text(f"## RULES\n{RULE}\n")

    assert ledger.snapshot("Added the probe rule; tidied nothing else.") == 0

    subject = _run_git(repo, "log", "-n1", "--format=%s").strip()
    assert subject.startswith(ledger.SNAPSHOT_PREFIX)
    assert dt.date.today().isoformat() in subject
    assert _run_git(repo, "log", "-n1", "--format=%b").strip() == "Added the probe rule; tidied nothing else."


def test_snapshot_checkpoints_the_whole_days_work(memory):
    """The dream commit is the box's nightly checkpoint: every changed file rides in it, not just
    MEMORY.md."""
    repo = memory.parents[1]
    memory.write_text(f"## RULES\n{RULE}\n")
    (repo / "agent" / "notes.md").write_text("day work\n")

    assert ledger.snapshot("Rules plus a day note.") == 0

    files = _run_git(repo, "show", "--name-only", "--format=", "HEAD")
    assert "agent/MEMORY.md" in files and "agent/notes.md" in files


def test_main_snapshot_without_a_summary_is_a_usage_error_without_committing(memory, monkeypatch, capsys):
    memory.write_text(f"## RULES\n{RULE}\n")
    monkeypatch.setattr("sys.argv", ["memory_ledger.py", "--snapshot"])

    assert ledger.main() != 0

    assert "usage:" in capsys.readouterr().err
    assert ledger.SNAPSHOT_PREFIX not in _run_git(memory.parents[1], "log", "--format=%s")


def test_snapshot_is_a_quiet_noop_mid_merge(memory, capsys):
    repo = memory.parents[1]
    memory.write_text(f"## RULES\n{RULE}\n")
    (repo / ".git" / "MERGE_HEAD").write_text(_run_git(repo, "rev-parse", "HEAD"))

    assert ledger.snapshot("Never lands.") == 0

    assert "merge in progress" in capsys.readouterr().out
    assert ledger.SNAPSHOT_PREFIX not in _run_git(repo, "log", "--format=%s")


def test_snapshot_is_a_quiet_noop_on_a_clean_tree(memory, capsys):
    assert ledger.snapshot("Never lands.") == 0

    assert "nothing changed" in capsys.readouterr().out
    assert ledger.SNAPSHOT_PREFIX not in _run_git(memory.parents[1], "log", "--format=%s")


def test_a_checkpoint_predating_the_file_reads_as_an_empty_baseline(memory, capsys):
    repo = memory.parents[1]
    _run_git(repo, "rm", "-q", ledger.REL)
    _run_git(repo, "commit", "-q", "-m", f"{ledger.SNAPSHOT_PREFIX} (2020-01-01)", "-m", "Before the file existed.")
    (repo / "agent").mkdir(exist_ok=True)
    memory.write_text(f"## RULES\n{RULE}\n")

    assert ledger.report() == 0

    assert "0 durable line(s) lost" in capsys.readouterr().out


def test_report_errors_on_stderr_outside_a_git_checkout(tmp_path, monkeypatch, capsys):
    (tmp_path / "agent").mkdir()
    mem = tmp_path / "agent" / "MEMORY.md"
    mem.write_text(f"## RULES\n{RULE}\n")
    monkeypatch.setattr(ledger, "REPO", tmp_path)
    monkeypatch.setattr(ledger, "MEMORY", mem)

    assert ledger.report() != 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""
