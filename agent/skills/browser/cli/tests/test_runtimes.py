from vesta_browser.runtimes import ExecOutcome


def test_exec_outcome_defaults_to_an_empty_warnings_list():
    assert ExecOutcome("", "", 0, 1).warnings == []


def test_exec_outcome_instances_do_not_share_the_warnings_list():
    first = ExecOutcome("", "", 0, 1)
    second = ExecOutcome("", "", 0, 1)
    first.warnings.append("boom")
    assert second.warnings == []
