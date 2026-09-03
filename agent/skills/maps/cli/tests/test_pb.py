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


def test_build_search_pb_near_prepends_viewport():
    pb = build_search_pb("gelato", "TOK123", near=(40.5589, 8.3138))
    assert pb.startswith("!4m12!1m3!1d")
    assert "!2d8.3138!3d40.5589" in pb
    assert "1sgelato" in pb
    assert "1sTOK123" in pb


def test_build_search_pb_without_near_has_no_viewport():
    pb = build_search_pb("gelato", "TOK123")
    assert not pb.startswith("!4m")
