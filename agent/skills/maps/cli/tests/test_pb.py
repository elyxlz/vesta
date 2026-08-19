from pathlib import Path

from gmaps_cli.pb import build_search_pb, extract_session_token, strip_envelope

FIXTURES = Path(__file__).parent / "fixtures"


def test_strip_envelope():
    assert strip_envelope(")]}'\n[1,2]") == "[1,2]"
    assert strip_envelope("[1,2]") == "[1,2]"


def test_extract_session_token():
    html = (FIXTURES / "search_page.html").read_text(encoding="utf-8")
    token = extract_session_token(html)
    assert 22 <= len(token) <= 24
    assert token.replace("-", "").replace("_", "").isalnum()


def test_build_search_pb_slots_query_and_token():
    pb = build_search_pb("gelato", "TOK123")
    assert "1sgelato" in pb
    assert "1sTOK123" in pb
    assert "{QUERY}" not in pb
    assert "{TOKEN}" not in pb
