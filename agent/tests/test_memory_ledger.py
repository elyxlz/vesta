"""Tests for the dream skill's memory_ledger script: durable-line extraction + lost vs reworded."""

import importlib.util
import pathlib as pl

import pytest

SCRIPT = pl.Path(__file__).resolve().parents[1] / "skills" / "dream" / "scripts" / "memory_ledger.py"

spec = importlib.util.spec_from_file_location("memory_ledger", SCRIPT)
assert spec is not None and spec.loader is not None
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)

RULE = "- WHEN a probe's success is itself the damage -> there is no safe way to run it live."
OTHER = "- WHEN a number moves and I reach for a cause -> check the number is even measuring me."


@pytest.fixture
def memory(tmp_path, monkeypatch):
    """Point the ledger at a throwaway MEMORY.md and snapshot dir, and hand back both paths."""
    mem, snaps = tmp_path / "MEMORY.md", tmp_path / "snapshots"
    monkeypatch.setattr(ledger, "MEMORY", mem)
    monkeypatch.setattr(ledger, "SNAPS", snaps)
    return mem, snaps


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
    mem, _ = memory
    mem.write_text(f"## RULES\n{RULE}\n{OTHER}\n")
    ledger.snapshot()
    mem.write_text(f"## RULES\n{RULE.replace('no safe way', 'no defensible way')}\n")

    ledger.report()

    out = capsys.readouterr().out
    assert "1 durable line(s) lost, 1 reworded" in out
    assert "no defensible way" in out
    assert OTHER in out


def test_report_is_clean_when_only_the_volatile_sections_changed(memory, capsys):
    mem, _ = memory
    mem.write_text(f"## RULES\n{RULE}\n### User State\n**Focus**: yesterday's read\n")
    ledger.snapshot()
    mem.write_text(f"## RULES\n{RULE}\n### User State\n**Focus**: a completely different read\n")

    ledger.report()

    assert "0 durable line(s) lost, 0 reworded" in capsys.readouterr().out


def test_report_says_so_when_there_is_no_baseline_yet(memory, capsys):
    """The first run on a new agent: no snapshot has ever been taken, so the directory is absent."""
    mem, _ = memory
    mem.write_text(f"## RULES\n{RULE}\n")

    ledger.report()

    assert "no prior snapshot" in capsys.readouterr().out


def test_snapshot_prunes_beyond_the_keep_window(memory, capsys):
    mem, snaps = memory
    mem.write_text(f"## RULES\n{RULE}\n")
    snaps.mkdir()
    for day in range(1, ledger.KEEP + 2):
        (snaps / f"2020-01-{day:02d}.md").write_text("old")

    ledger.snapshot()

    kept = sorted(p.name for p in snaps.glob("*.md"))
    assert len(kept) == ledger.KEEP
    assert "2020-01-01.md" not in kept
