import pytest
from upstream_cli.titles import title_errors, title_warnings


@pytest.mark.parametrize(
    "title",
    [
        "fix(skills/restart): retry a failed daemon start",
        "feat(upstream): wrap gh with injected auth",
        "docs(migrations): state the append-only rule",
    ],
)
def test_conforming_titles_have_no_errors(title):
    assert title_errors(title) == []


@pytest.mark.parametrize(
    ("title", "fragment"),
    [
        ("Fix(skills): retry", "type"),
        ("wip(skills): retry", "type"),
        ("fix: retry a failed start", "scope"),
        ("fix(Skills): retry", "scope"),
        ("fix(skills): Retry the start", "lowercase"),
        ("fix(skills): retry the start.", "period"),
        ("just a sentence", "type"),
    ],
)
def test_nonconforming_titles_report_the_broken_rule(title, fragment):
    errors = title_errors(title)
    assert errors, title
    assert any(fragment in e for e in errors), errors


def test_long_title_warns_but_is_not_an_error():
    title = "fix(skills/restart): " + "a" * 80
    assert title_errors(title) == []
    assert title_warnings(title)
