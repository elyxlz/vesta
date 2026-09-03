"""A body that names the owner is refused before anything reaches GitHub.

Identity is read from the box, so each test writes its own under the scratch HOME conftest gives
every test; nothing here depends on the machine running the suite."""

import json

import pytest
from upstream_cli import cli

from tests.test_dispatch import run_main

OWNER_PROFILE = "## 4. USER PROFILE\n- **Name**: Zephrine Al Quillbrook\n"
UNBORN_PROFILE = "## 4. USER PROFILE\n- **Name**: [Unknown]  (identity sentinel: keep it verbatim until birth fills it)\n"


@pytest.fixture
def box(scratch_home):
    """An owner in MEMORY.md section 4 and one contact file, laid out as a box holds them."""
    (scratch_home / "agent").mkdir()
    (scratch_home / "agent" / "MEMORY.md").write_text(OWNER_PROFILE)
    (scratch_home / ".contacts").mkdir()
    (scratch_home / ".contacts" / "vandersloot-cofounder.md").write_text("# Q Vandersloot\n")
    return scratch_home


@pytest.mark.parametrize(
    ("body", "kind"),
    [
        ("Zephrine asked for this", "the user's name"),
        ("as QUILLBROOK's box does", "the user's name"),
        ("vandersloot reported it", "a contact's name"),
        ("(Vandersloot)", "a contact's name"),
    ],
)
def test_a_body_naming_the_owner_or_a_contact_is_refused_by_kind(box, body, kind):
    assert cli.refuse_identifying(body) == kind


@pytest.mark.parametrize(
    "body",
    [
        "describe the pattern, not the person",
        "Zephrines and Quillbrooks are not whole words",
        "Al is under four letters and not checked",
        "",
    ],
)
def test_a_clean_body_passes(box, body):
    assert cli.refuse_identifying(body) is None


def test_the_identity_sentinel_and_its_annotation_name_nobody(scratch_home):
    (scratch_home / "agent").mkdir()
    (scratch_home / "agent" / "MEMORY.md").write_text(UNBORN_PROFILE)
    assert cli.refuse_identifying("unknown identity sentinel, verbatim until birth") is None


def test_a_box_with_no_memory_and_no_contacts_refuses_nothing(scratch_home):
    assert cli.refuse_identifying("Zephrine") is None


def test_pr_create_refuses_before_pushing_and_never_prints_the_name(box, monkeypatch, capsys):
    monkeypatch.setattr(cli, "submit_pr", lambda args: pytest.fail("pushed a body naming the owner"))
    assert run_main(monkeypatch, ["gh", "pr", "create", "--title", "fix(a): b", "--body", "Zephrine saw this"]) == 1
    err = capsys.readouterr().err
    assert "body names the owner (the user's name); describe the pattern, not the person" in err
    assert "Zephrine" not in err


def test_issue_create_refuses_before_any_gh_call(box, monkeypatch, fake_gh, agent_identity, capsys):
    record, _, _ = fake_gh
    assert run_main(monkeypatch, ["gh", "issue", "create", "--title", "fix(a): b", "--body", "for vandersloot"]) == 1
    assert "a contact's name" in capsys.readouterr().err
    assert not record.exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["pr", "comment", "12", "--body", "Zephrine again"],
        ["pr", "comment", "12", "--body=Zephrine again"],
        ["issue", "comment", "12", "-b", "Zephrine again"],
    ],
)
def test_a_comment_body_is_checked_in_every_flag_spelling(box, monkeypatch, fake_gh, capsys, argv):
    record, _, _ = fake_gh
    assert run_main(monkeypatch, ["gh", *argv]) == 1
    assert "the user's name" in capsys.readouterr().err
    assert not record.exists()


def test_a_clean_comment_passes_through_untouched(box, monkeypatch, fake_gh):
    record, _, _ = fake_gh
    assert run_main(monkeypatch, ["gh", "pr", "comment", "12", "--body", "the pattern, not the person"]) == 0
    assert json.loads(record.read_text())["argv"] == ["pr", "comment", "12", "--body", "the pattern, not the person"]
