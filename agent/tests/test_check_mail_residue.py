"""The mail residue check lists files outside the mail stores that hold mailbox content."""

import os
import pathlib as pl
import subprocess

import pytest

SCRIPT = pl.Path(__file__).resolve().parents[1] / "skills" / "dream" / "scripts" / "check_mail_residue.sh"

MAIL_API_DUMP = '[{"subject": "Invoice", "bodyPreview": "Please find attached", "receivedDateTime": "2026-01-01T00:00:00Z"}]'
ITEM_ID_ROW = "Invoice\tAAMkADcontrolcontrolcontrolcontrolcontrolcontrolcontrol0123456789=\t2026-01-01\n"


def _run(home: pl.Path, *roots: pl.Path) -> subprocess.CompletedProcess[str]:
    # The default roots include the temp dir, which is the machine's when the script reads /tmp, so
    # the test pins it under the scratch home to stay hermetic.
    env = {**os.environ, "HOME": str(home), "TMPDIR": str(home / "tmp")}
    return subprocess.run(["bash", str(SCRIPT), *map(str, roots)], env=env, capture_output=True, text=True, timeout=60, check=False)


def _roster(count: int) -> str:
    return "\n".join(f"person{n}@example{n}.org" for n in range(count))


def test_a_workspace_of_prose_is_clean_and_silent(tmp_path):
    root = tmp_path / "scratch"
    root.mkdir()
    (root / "notes.md").write_text("Reply to alice@example.com and cc bob@example.org about the invoice.\n")

    run = _run(tmp_path, root)

    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stdout == ""


@pytest.mark.parametrize(
    ("name", "content"),
    [("dump.json", MAIL_API_DUMP), ("index.tsv", ITEM_ID_ROW), ("roster.txt", _roster(25))],
    ids=["mail-api-dump", "exchange-item-id", "address-roster"],
)
def test_mailbox_content_is_listed_once_by_path(tmp_path, name, content):
    root = tmp_path / "scratch"
    root.mkdir()
    (root / name).write_text(content)

    run = _run(tmp_path, root)

    assert run.returncode == 1
    assert run.stdout == f"{root / name}\n"


def test_a_file_matching_both_rules_is_listed_once(tmp_path):
    root = tmp_path / "scratch"
    root.mkdir()
    (root / "dump.json").write_text(MAIL_API_DUMP + "\n" + _roster(30))

    run = _run(tmp_path, root)

    assert run.stdout == f"{root / 'dump.json'}\n"


def test_a_short_address_list_is_prose(tmp_path):
    root = tmp_path / "scratch"
    root.mkdir()
    (root / "contacts.txt").write_text(_roster(24))

    run = _run(tmp_path, root)

    assert run.returncode == 0
    assert run.stdout == ""


@pytest.mark.parametrize(
    "relative", ["tool.py", "node_modules/pkg/fixture.json", ".git/objects/blob", ".venv/lib/data.json", "agent/data/events.db"]
)
def test_code_pruned_trees_and_the_events_db_are_not_listed(tmp_path, relative):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(MAIL_API_DUMP)

    run = _run(tmp_path, tmp_path)

    assert run.returncode == 0, run.stdout
    assert run.stdout == ""


def test_default_roots_cover_the_agent_workspace_and_the_temp_dir(tmp_path):
    (tmp_path / "agent").mkdir()
    (tmp_path / "tmp").mkdir()
    (tmp_path / "agent" / "mail-export.json").write_text(MAIL_API_DUMP)
    (tmp_path / "tmp" / "scratch.tsv").write_text(ITEM_ID_ROW)

    run = _run(tmp_path)

    assert run.returncode == 1
    assert run.stdout.splitlines() == [str(tmp_path / "agent" / "mail-export.json"), str(tmp_path / "tmp" / "scratch.tsv")]


def test_missing_roots_are_clean(tmp_path):
    run = _run(tmp_path, tmp_path / "absent")

    assert run.returncode == 0
    assert run.stdout == ""
