"""Behavioral tests for upstream-pr/scripts/gate2b-check.sh.

Every case is derived from a diff the gate exists to reject or to leave alone, never from reading
the script's own patterns: a case built from the implementation can only confirm that the code
agrees with itself, and it passes every mutation that leaves the script running.

The negative cases carry the weight. A lint that flags everything is indistinguishable from one
that works, until it has trained everyone to skim it.
"""

import pathlib as pl
import subprocess

SCRIPT = pl.Path(__file__).resolve().parents[1] / "skills" / "upstream-pr" / "scripts" / "gate2b-check.sh"


def repo(tmp_path: pl.Path) -> pl.Path:
    """A git repo with one committed file under agent/, so added lines have something to diff."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(tmp_path), "config", k, v], check=True)
    d = tmp_path / "agent" / "skills" / "x"
    d.mkdir(parents=True)
    (d / "d.py").write_text("x = 1\n")
    (d / "S.md").write_text("doc\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], check=True)
    return tmp_path


def add(tmp_path: pl.Path, name: str, line: str) -> int:
    """Append one line to a tracked file and return the check's exit code."""
    f = tmp_path / "agent" / "skills" / "x" / name
    f.write_text(f.read_text() + line + "\n")
    return subprocess.run([str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True, check=False).returncode


def test_narrating_the_previous_wording_is_flagged(tmp_path):
    assert add(repo(tmp_path), "d.py", "# Previously this returned the stock file and exited 0.") == 1


def test_x_not_y_default_is_flagged(tmp_path):
    """The shape a maintainer caught across eight daemon comments: the new value against the old."""
    assert add(repo(tmp_path), "d.py", "# 120, not 30. A readiness budget is a bet about disk speed.") == 1


def test_a_dated_observation_is_flagged(tmp_path):
    assert add(repo(tmp_path), "d.py", "# Always pass --frozen. Observed 17 Aug: it re-upgraded the lock.") == 1


def test_a_bare_date_is_flagged_without_a_trigger_verb(tmp_path):
    """The gate cuts the date whatever the sentence does with it, so no nearby verb is required."""
    assert add(repo(tmp_path), "d.py", "# so on 18 Aug 2026, when the shims went missing, three daemons were DOWN") == 1


def test_an_iso_date_in_prose_is_flagged(tmp_path):
    assert add(repo(tmp_path), "S.md", "Cherry-picked 2026-08-14 from upstream after it broke here.") == 1


def test_plain_mechanism_prose_is_not_flagged(tmp_path):
    assert add(repo(tmp_path), "d.py", "# The daemon returns the moment the port answers; pass the env var to override.") == 0


def test_code_containing_a_numeral_pair_is_not_flagged(tmp_path):
    """Only comments and markdown are prose. Code that happens to read like a pair is not narration."""
    assert add(repo(tmp_path), "d.py", "retries = max(120, not_before)") == 0


def test_numbers_without_a_month_name_are_not_flagged(tmp_path):
    assert add(repo(tmp_path), "d.py", "# Run the cron 0 9 * * 1-5 and keep the 2119 limit in mind.") == 0


def test_a_quoted_date_is_a_format_example_not_a_narration(tmp_path):
    """`--at "2026-12-01T10:00:00"` teaches the reader a format; it does not date an incident."""
    assert add(repo(tmp_path), "S.md", 'tasks create "Meeting prep" --at "2026-12-01T10:00:00"') == 0


def test_a_backticked_dated_filename_is_not_flagged(tmp_path):
    assert add(repo(tmp_path), "S.md", "One directory per job, `2026-08-15-cover-letter-acme/`, holding brief.md.") == 0


def test_a_bad_revision_exits_two_rather_than_reporting_clean(tmp_path):
    """An unreadable diff is UNMEASURED. Exiting 0 there is the failure the whole script guards."""
    r = subprocess.run([str(SCRIPT), "nosuchref123", "HEAD"], cwd=repo(tmp_path), capture_output=True, text=True, check=False)
    assert r.returncode == 2
    assert "NOT checked" in r.stderr


def test_an_empty_diff_says_nothing_was_judged_rather_than_clean(tmp_path):
    r = subprocess.run([str(SCRIPT)], cwd=repo(tmp_path), capture_output=True, text=True, check=False)
    assert r.returncode == 0
    assert "nothing was judged" in r.stdout


def test_a_brand_new_untracked_file_is_judged(tmp_path):
    """A file git has never seen has no diff, so a whole new SKILL.md would otherwise sail through
    with every one of its lines unread. The default invocation synthesizes the added-line form."""
    r = repo(tmp_path)
    (r / "agent" / "skills" / "x" / "NEW.md").write_text("Previously this returned the stock file.\n")
    p = subprocess.run([str(SCRIPT)], cwd=r, capture_output=True, text=True, check=False)
    assert p.returncode == 1
    assert "NEW.md" in p.stdout


def test_an_untracked_file_outside_agent_is_ignored(tmp_path):
    r = repo(tmp_path)
    (r / "NOTES.md").write_text("Previously this returned the stock file.\n")
    p = subprocess.run([str(SCRIPT)], cwd=r, capture_output=True, text=True, check=False)
    assert p.returncode == 0
