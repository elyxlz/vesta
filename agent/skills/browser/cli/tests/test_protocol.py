import pytest
from vesta_browser import protocol as p


def test_error_carries_every_required_field():
    err = p.error("timed_out", "execution", "budget exhausted", retryable=True, suggested_action="raise --timeout")
    assert err == {
        "code": "timed_out",
        "phase": "execution",
        "message": "budget exhausted",
        "retryable": True,
        "suggested_action": "raise --timeout",
    }


def test_error_rejects_unknown_code_and_phase():
    with pytest.raises(ValueError):
        p.error("nope", "execution", "m", retryable=False, suggested_action="s")
    with pytest.raises(ValueError):
        p.error("timed_out", "nope", "m", retryable=False, suggested_action="s")


def test_result_defaults_every_optional_component_explicitly():
    res = p.result(request_id="r1", op="status", ok=True)
    assert res["schema"] == p.SCHEMA
    assert res["session"] is None and res["page"] is None and res["output"] is None
    assert res["artifacts"] == [] and res["warnings"] == [] and res["error"] is None and res["data"] is None


def test_failed_result_keeps_verified_context():
    err = p.error("execution_failed", "execution", "boom", retryable=False, suggested_action="fix the code")
    session = p.session_info("research", "standard", "chromium", "ready")
    res = p.result(request_id="r1", op="exec", ok=False, session=session, page=p.page_unavailable(), err=err)
    assert res["ok"] is False and res["error"] == err
    assert res["session"]["engine"] == "chromium" and res["session"]["protocol"] == "cdp"
    assert res["page"] == {"state": "unavailable"}


def test_truncate_reports_whether_it_cut():
    assert p.truncate("abc", 10) == ("abc", False)
    text, cut = p.truncate("x" * 20, 10)
    assert cut is True and len(text.encode()) <= 10


def test_mode_engine_tables_agree():
    assert p.ENGINE_FOR_MODE == {"standard": "chromium", "stealth": "camoufox"}
    assert p.PROTOCOL_FOR_ENGINE == {"chromium": "cdp", "camoufox": "playwright-firefox"}
    assert "cdp" in p.EXTENSIONS_FOR_ENGINE["chromium"] and "playwright-page" in p.EXTENSIONS_FOR_ENGINE["camoufox"]


def test_session_name_pattern():
    assert p.SESSION_NAME_RE.match("default")
    assert p.SESSION_NAME_RE.match("microsoft-alice_example")
    assert not p.SESSION_NAME_RE.match("Has.Dot")
    assert not p.SESSION_NAME_RE.match("-lead")
    assert not p.SESSION_NAME_RE.match("a" * 65)


def test_now_iso_is_utc_zulu():
    assert p.now_iso().endswith("Z") and "T" in p.now_iso()
