import json

import pytest
from upstream_cli import cli

from tests.conftest import SENTINEL


def run_main(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["upstream", *argv])
    try:
        cli.main()
    except SystemExit as stop:
        return int(stop.code or 0)
    return 0


class FakePR:
    """The PR as GitHub serves it: a PATCH writes the fields, a GET replays what is stored.

    `applies_writes = False` is the failure this interception exists for, a write that answers 200
    and changes nothing, so the suite can prove the read-back catches it."""

    def __init__(self):
        self.fields = {"title": "fix(a): as first filed", "body": "as first filed"}
        self.calls = []
        self.applies_writes = True
        self.read_code = 0

    def gh_api(self, token, path, *, method="GET", fields=None):
        self.calls.append((method, path, fields))
        if method == "PATCH":
            if self.applies_writes:
                self.fields.update(fields)
            return 0, json.dumps(self.served())
        if self.read_code != 0:
            return self.read_code, "gh: could not resolve host api.github.com"
        return 0, json.dumps(self.served())

    def served(self):
        return {"number": 7, "html_url": "https://github.com/elyxlz/vesta/pull/7", **self.fields}


@pytest.fixture
def fake_pr(monkeypatch, agent_identity):
    pr = FakePR()
    monkeypatch.setattr(cli, "gh_api", pr.gh_api)
    monkeypatch.setattr(cli, "get_installation_token", lambda: SENTINEL)
    return pr


def test_a_title_edit_patches_then_reads_the_title_back(monkeypatch, fake_pr, capsys):
    assert run_main(monkeypatch, ["gh", "pr", "edit", "7", "--title", "fix(a): the corrected title"]) == 0
    assert fake_pr.fields["title"] == "fix(a): the corrected title"
    assert fake_pr.fields["body"] == "as first filed"
    methods = [method for method, _, _ in fake_pr.calls]
    assert methods == ["PATCH", "GET"]
    assert fake_pr.calls[0][1] == "repos/elyxlz/vesta/pulls/7"
    assert "updated" in capsys.readouterr().out


def test_a_body_edit_carries_the_footer_once(monkeypatch, fake_pr):
    assert run_main(monkeypatch, ["gh", "pr", "edit", "7", "--body", "the corrected body"]) == 0
    assert fake_pr.fields["body"] == "the corrected body\n\n---\nSubmitted by **tester** on vesta v9.9.9"
    assert "title" not in fake_pr.calls[0][2]

    resubmitted = fake_pr.fields["body"]
    assert run_main(monkeypatch, ["gh", "pr", "edit", "7", "--body", resubmitted]) == 0
    assert fake_pr.fields["body"] == resubmitted


def test_the_footer_shape_matches_the_footer_the_cli_writes():
    """One owner for the wording: the pattern that detects a footer must match the line written."""
    assert cli.ATTRIBUTION_SHAPE.search(cli.attribution_line("tester", "9.9.9"))


def test_a_body_filed_under_another_version_keeps_exactly_one_footer(monkeypatch, fake_pr):
    """A PR filed on one version and edited on another: the footer is matched by shape, not text."""
    filed = "as first filed\n\n---\nSubmitted by **someone-else** on vesta v0.0.1"
    fake_pr.fields["body"] = filed
    assert run_main(monkeypatch, ["gh", "pr", "edit", "7", f"--body={filed}\n\nand a new paragraph"]) == 0
    assert fake_pr.fields["body"].count("Submitted by") == 1
    assert fake_pr.fields["body"].endswith("Submitted by **someone-else** on vesta v0.0.1\n\nand a new paragraph")


def test_a_body_file_is_read_from_disk(monkeypatch, fake_pr, tmp_path):
    body = tmp_path / "body.md"
    body.write_text("from a file")
    assert run_main(monkeypatch, ["gh", "pr", "edit", "7", "--body-file", str(body)]) == 0
    assert fake_pr.fields["body"].startswith("from a file")


def test_an_unsupported_flag_is_refused_and_nothing_is_written(monkeypatch, fake_pr, capsys):
    assert run_main(monkeypatch, ["gh", "pr", "edit", "7", "--add-label", "bug"]) == 2
    assert "--add-label" in capsys.readouterr().err
    assert fake_pr.calls == []
    assert fake_pr.fields["title"] == "fix(a): as first filed"


def test_a_write_that_does_not_land_exits_nonzero(monkeypatch, fake_pr, capsys):
    """The whole bug: an edit that reports success and leaves the old text live."""
    fake_pr.applies_writes = False
    assert run_main(monkeypatch, ["gh", "pr", "edit", "7", "--title", "fix(a): the corrected title"]) == 1
    err = capsys.readouterr().err
    assert "did NOT land" in err and "title" in err


def test_an_unreadable_pr_after_the_patch_reports_the_edit_as_unverified(monkeypatch, fake_pr, capsys):
    fake_pr.read_code = 1
    assert run_main(monkeypatch, ["gh", "pr", "edit", "7", "--body", "b"]) == 1
    assert "UNVERIFIED" in capsys.readouterr().err


def test_crlf_line_endings_from_github_still_read_as_a_match(monkeypatch, fake_pr):
    monkeypatch.setattr(cli, "body_with_attribution", lambda body, *identity: body)
    original_gh_api = fake_pr.gh_api

    def crlf_gh_api(token, path, *, method="GET", fields=None):
        code, out = original_gh_api(token, path, method=method, fields=fields)
        return code, out.replace("\\n", "\\r\\n")

    monkeypatch.setattr(cli, "gh_api", crlf_gh_api)
    assert run_main(monkeypatch, ["gh", "pr", "edit", "7", "--body", "line one\nline two"]) == 0


def test_a_nonconforming_new_title_is_refused_before_any_write(monkeypatch, fake_pr, capsys):
    assert run_main(monkeypatch, ["gh", "pr", "edit", "7", "--title", "Bad Title"]) == 1
    assert "type(scope)" in capsys.readouterr().err
    assert fake_pr.calls == []


def test_edit_needs_a_pr_number_and_something_to_change(monkeypatch, fake_pr, capsys):
    assert run_main(monkeypatch, ["gh", "pr", "edit", "--body", "b"]) == 2
    assert "number" in capsys.readouterr().err
    assert run_main(monkeypatch, ["gh", "pr", "edit", "7"]) == 2
    assert "nothing to edit" in capsys.readouterr().err
    assert fake_pr.calls == []


def test_body_and_body_file_together_are_refused(monkeypatch, fake_pr, tmp_path, capsys):
    assert run_main(monkeypatch, ["gh", "pr", "edit", "7", "--body", "b", "--body-file", str(tmp_path / "x.md")]) == 2
    assert "not both" in capsys.readouterr().err
    assert fake_pr.calls == []
