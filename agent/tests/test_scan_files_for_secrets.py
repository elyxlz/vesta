"""Exercises scan_files_for_secrets.sh, the filesystem half of the nightly secret sweep.

redact_secrets.sh reads events.db and the channel stores, so a credential written to a FILE is
invisible to it and the sweep reports clean while the file sits there. Two failure classes are
pinned here, both of which make the report untrustworthy rather than merely incomplete: a root that
does not exist must never read as a clean root, and a name rule wide enough to match `tokenize.py`
buries the real hits under the standard library.
"""

import pathlib as pl
import subprocess

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "agent/skills/dream/scripts/scan_files_for_secrets.sh"

# Shaped like a GitHub App installation token, and deliberately not one.
FAKE_TOKEN = "ghs_" + "A1b2C3d4E5" * 4


def _run(*roots: object) -> subprocess.CompletedProcess[str]:
    """Roots are separate arguments, one per root.

    They used to be joined into a single whitespace separated argument, which made a path
    containing a space unrepresentable and only worked because the script re-split it. Passing
    them separately is what a shell caller does, and it is the form the roots loop now reads.
    """
    return subprocess.run(["sh", str(SCRIPT), *(str(r) for r in roots)], capture_output=True, text=True, timeout=180, check=False)


def test_a_clean_tree_exits_zero(tmp_path):
    # The healthy case is exercised on purpose: a scan that cannot come back clean is as broken as
    # one that cannot find anything.
    (tmp_path / "notes.md").write_text("nothing interesting here\n")

    run = _run(tmp_path)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "no credential-shaped files found" in run.stdout


def test_a_token_in_a_file_is_found_by_content_and_never_printed(tmp_path):
    # Printing the value to report the value is how a credential ends up back in the event store.
    (tmp_path / "note.txt").write_text(f"TOKEN={FAKE_TOKEN}\n")

    run = _run(tmp_path)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "note.txt" in run.stdout
    assert "by CONTENT" in run.stdout
    assert FAKE_TOKEN not in run.stdout + run.stderr


def test_a_private_key_block_is_found_by_content(tmp_path):
    (tmp_path / "backup.dat").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk=\n")

    run = _run(tmp_path)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "by CONTENT" in run.stdout


def test_a_credential_store_is_found_by_name_whatever_it_holds(tmp_path):
    # A passphrase or a human-chosen password matches no content pattern at all, so the name of the
    # file it lives in is the only signal there is.
    (tmp_path / ".env").write_text("DB_PASSWORD=correct horse battery staple\n")

    run = _run(tmp_path)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "by NAME" in run.stdout


def test_source_files_that_merely_say_token_or_secret_are_not_hits(tmp_path):
    # A bare `*token*` or `*secret*` rule matches half the standard library, and a report padded
    # with source files gets skimmed, which is the same as not having one.
    for name in ("tokenize.py", "token.h", "secrets.py", "design-tokens.css", "secretary.md"):
        (tmp_path / name).write_text("import sys\n")

    run = _run(tmp_path)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "HIT" not in run.stdout


def test_a_root_that_does_not_exist_is_not_a_clean_root(tmp_path):
    # The failure this whole script exists for, one level up: a scan that could not have found
    # anything must not report that it found nothing.
    run = _run(tmp_path / "no-such-dir")

    assert run.returncode == 2, run.stdout + run.stderr
    assert "not a clean result" in run.stderr
    assert "no credential-shaped files found" not in run.stdout


def test_a_missing_root_beside_a_real_one_is_reported_and_the_real_one_is_scanned(tmp_path):
    (tmp_path / "note.txt").write_text(f"TOKEN={FAKE_TOKEN}\n")

    run = _run(tmp_path / "no-such-dir", tmp_path)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "was NOT scanned" in run.stderr
    assert "by CONTENT" in run.stdout


def test_package_caches_and_the_git_object_store_are_pruned(tmp_path):
    for pruned in (".git", "node_modules", ".venv"):
        directory = tmp_path / pruned
        directory.mkdir()
        (directory / "blob").write_text(f"TOKEN={FAKE_TOKEN}\n")

    run = _run(tmp_path)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "HIT" not in run.stdout


def test_the_callers_cwd_cannot_blind_the_by_name_scan(tmp_path):
    # The name patterns are arguments for find, not paths in the caller's shell. When they were
    # left to glob, two matching files in the cwd turned one `-name` into two words, find rejected
    # the whole expression, the error was swallowed, and the scan printed a confident all-clear
    # while a real credential store sat in the root it was pointed at.
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "a.key").write_text("")
    (cwd / "b.key").write_text("")
    target = tmp_path / "target"
    target.mkdir()
    (target / ".env").write_text("PASSPHRASE=hunter2\n")

    run = subprocess.run(["sh", str(SCRIPT), str(target)], capture_output=True, text=True, timeout=180, check=False, cwd=cwd)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "by NAME" in run.stdout
    assert ".env" in run.stdout


def test_roots_with_a_space_in_the_path_are_one_root_not_two(tmp_path):
    # The old interface joined roots into a single whitespace separated argument and re-split it,
    # so a directory whose name contains a space could not be expressed at all.
    spaced = tmp_path / "my documents"
    spaced.mkdir()
    (spaced / "note.txt").write_text(f"TOKEN={FAKE_TOKEN}\n")

    run = _run(spaced)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "was NOT scanned" not in run.stderr
    assert "by CONTENT" in run.stdout
