"""`email diff`: line normalization, and a named verdict for every outcome."""

from google_cli import gmail

# -- _normalize_body_lines ---------------------------------------------


def test_blank_lines_dropped():
    assert gmail._normalize_body_lines("a\n\n\nb\n") == ["a", "b"]


def test_trailing_whitespace_stripped():
    assert gmail._normalize_body_lines("hello   \n") == ["hello"]


def test_angle_wrapped_tracker_url_removed():
    lines = gmail._normalize_body_lines("Click here <https://track.example/abc123?u=99>")
    assert lines == ["Click here"]


def test_bare_url_collapsed_to_placeholder():
    lines = gmail._normalize_body_lines("see https://track.example/x?token=1 now")
    assert lines == ["see <link> now"]


def test_two_sends_differing_only_in_tracker_token_normalize_equal():
    first = gmail._normalize_body_lines("Confirm <https://t.example/a?tok=111>")
    second = gmail._normalize_body_lines("Confirm <https://t.example/a?tok=222>")
    assert first == second


def test_real_wording_change_survives_normalization():
    first = gmail._normalize_body_lines("Please wear the following items to your interview")
    second = gmail._normalize_body_lines("Please wear the following items to your interview if you have them;")
    assert first != second


# -- diff_emails verdicts ----------------------------------------------


class _Config:
    pass


def _patch(monkeypatch, matches, bodies):
    monkeypatch.setattr(gmail, "search_emails", lambda config, **kw: matches)
    monkeypatch.setattr(gmail.api, "gmail_service", lambda config: object())
    monkeypatch.setattr(gmail, "_fetch_body_lines", lambda service, message_id: bodies[message_id])


def _msg(message_id, subject="Reminder"):
    return {"id": message_id, "date": f"date-{message_id}", "subject": subject}


def test_no_match_is_named_not_empty(monkeypatch):
    _patch(monkeypatch, [], {})
    result = gmail.diff_emails(_Config(), sender="nobody@example.com")
    assert result["verdict"] == "NO_MATCH"


def test_single_match_is_an_answer_not_a_failure(monkeypatch):
    _patch(monkeypatch, [_msg("one")], {})
    result = gmail.diff_emails(_Config(), sender="a@example.com")
    assert result["verdict"] == "ONLY_ONE_MATCH"
    assert "diff" not in result


def test_identical_bodies_report_no_textual_change(monkeypatch):
    _patch(monkeypatch, [_msg("new"), _msg("old")], {"new": ["same line"], "old": ["same line"]})
    result = gmail.diff_emails(_Config(), sender="a@example.com")
    assert result["verdict"] == "NO_TEXTUAL_CHANGE"
    assert result["changed_line_count"] == 0
    assert "diff" not in result


def test_changed_wording_is_reported_with_the_changed_line(monkeypatch):
    _patch(
        monkeypatch,
        [_msg("new"), _msg("old")],
        {
            "old": ["Bring your passport", "Please wear the uniform"],
            "new": ["Bring your passport", "Please wear the uniform if you have it"],
        },
    )
    result = gmail.diff_emails(_Config(), sender="a@example.com")
    assert result["verdict"] == "CHANGED"
    assert result["changed_line_count"] == 2
    assert any(line.startswith("+Please wear the uniform if you have it") for line in result["diff"])
    assert result["newer"]["id"] == "new"
    assert result["older"]["id"] == "old"


def test_subject_filter_is_quoted_into_the_query(monkeypatch):
    seen = {}

    def _search(config, **kw):
        seen["query"] = kw["query"]
        return []

    monkeypatch.setattr(gmail, "search_emails", _search)
    gmail.diff_emails(_Config(), sender="a@example.com", subject="Interview")
    assert seen["query"] == 'from:a@example.com subject:"Interview"'
