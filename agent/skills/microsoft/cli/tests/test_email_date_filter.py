"""Locks the date-range filter helpers for email list/search (--since/--until).

Plain search uses relevance-ranked $search, which buries old mail. The date flags
switch to a receivedDateTime $filter range; when a text query is also given, Graph
forbids $search + $filter together, so the query is matched client-side.
"""

from microsoft_cli import email, owa_rest_commands


def test_iso_utc_bound_start_and_end_of_day():
    assert email._iso_utc_bound("2021-01-01", end_of_day=False) == "2021-01-01T00:00:00Z"
    assert email._iso_utc_bound("2021-12-31", end_of_day=True) == "2021-12-31T23:59:59Z"


def test_iso_utc_bound_full_iso_datetime_normalizes_to_utc():
    assert email._iso_utc_bound("2021-06-15T12:00:00+02:00", end_of_day=False) == "2021-06-15T10:00:00Z"


def test_build_received_filter_both_bounds_inclusive():
    clause = email._build_received_filter("2021-01-01", "2021-12-31")
    assert clause == "receivedDateTime ge 2021-01-01T00:00:00Z and receivedDateTime le 2021-12-31T23:59:59Z"


def test_build_received_filter_single_bound():
    assert email._build_received_filter("2021-01-01", None) == "receivedDateTime ge 2021-01-01T00:00:00Z"
    assert email._build_received_filter(None, "2021-12-31") == "receivedDateTime le 2021-12-31T23:59:59Z"


def test_email_matches_query_across_subject_from_and_preview():
    msg = {
        "subject": "Quarterly Report",
        "bodyPreview": "please review the numbers",
        "from": {"emailAddress": {"address": "cfo@example.com", "name": "Dana Finance"}},
    }
    assert email._email_matches_query(msg, "quarterly")  # subject, case-insensitive
    assert email._email_matches_query(msg, "REVIEW")  # body preview
    assert email._email_matches_query(msg, "dana")  # sender name
    assert email._email_matches_query(msg, "cfo@example")  # sender address
    assert not email._email_matches_query(msg, "invoice")


def test_owa_date_filter_uses_pascalcase_property():
    clause = owa_rest_commands._owa_date_filter("2021-01-01", "2021-12-31")
    assert clause == "ReceivedDateTime ge 2021-01-01T00:00:00Z and ReceivedDateTime le 2021-12-31T23:59:59Z"
