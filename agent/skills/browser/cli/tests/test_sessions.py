import pytest
from vesta_browser import protocol as p
from vesta_browser import sessions as s
from vesta_browser.runtime_paths import load_paths


@pytest.fixture
def table(tmp_path):
    clock = {"now": 1000.0}
    return s.load_table(load_paths({}, tmp_path), clock=lambda: clock["now"]), clock


def test_new_session_pins_the_requested_mode_and_creates_its_dirs(table):
    table, _ = table
    session = s.resolve_session(table, "research", "stealth")
    assert session.engine == "camoufox" and session.mode == "stealth" and session.state == "stopped"
    assert session.profile_dir.is_dir() and session.profile_dir.parts[-2:] == ("camoufox", "research")
    assert session.scratch_dir.is_dir() and session.artifact_dir.is_dir()


def test_omitted_mode_defaults_to_standard_on_a_new_session(table):
    table, _ = table
    assert s.resolve_session(table, "default", None).engine == "chromium"


def test_omitted_mode_inherits_and_explicit_conflict_fails(table):
    table, _ = table
    s.resolve_session(table, "research", "stealth")
    assert s.resolve_session(table, "research", None).engine == "camoufox"
    with pytest.raises(p.BrowserError) as excinfo:
        s.resolve_session(table, "research", "standard")
    err = excinfo.value.err
    assert err["code"] == "session_engine_conflict" and err["phase"] == "routing"
    assert "camoufox" in err["message"] and "standard" in err["message"]


@pytest.mark.parametrize("name", ["", "Upper", "has.dot", "-lead", "a" * 65, "sp ace"])
def test_bad_names_are_invalid_requests(table, name):
    table, _ = table
    with pytest.raises(p.BrowserError) as excinfo:
        s.resolve_session(table, name, None)
    assert excinfo.value.err["code"] == "invalid_request"


def test_table_rebuilds_stopped_sessions_from_profile_dirs(tmp_path):
    paths = load_paths({}, tmp_path)
    (paths.profiles / "camoufox/microsoft-alice").mkdir(parents=True)
    (paths.profiles / "chromium/default").mkdir(parents=True)
    table = s.load_table(paths)
    assert {n: (x.engine, x.state) for n, x in table.sessions.items()} == {
        "microsoft-alice": ("camoufox", "stopped"),
        "default": ("chromium", "stopped"),
    }


def test_idle_sessions_are_ready_ones_past_the_idle_budget(table):
    table, clock = table
    ready = s.resolve_session(table, "a", None)
    s.mark(ready, "ready")
    busy = s.resolve_session(table, "b", None)
    s.mark(busy, "busy")
    clock["now"] += p.SESSION_IDLE_STOP_SECS + 1
    assert [x.name for x in s.idle_sessions(table)] == ["a"]
    s.touch(table, ready)
    assert s.idle_sessions(table) == []


def test_info_matches_the_wire_shape(table):
    table, _ = table
    session = s.resolve_session(table, "research", "stealth")
    assert s.info(session) == {
        "name": "research",
        "mode": "stealth",
        "engine": "camoufox",
        "protocol": "playwright-firefox",
        "state": "stopped",
    }
