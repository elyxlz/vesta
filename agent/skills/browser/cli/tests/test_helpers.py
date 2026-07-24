"""Unit tests for helpers that don't require a live browser."""

from __future__ import annotations

import base64

import pytest
from vesta_browser import helpers

# ── Recipe banner logic ────────────────────────────────────────


def test_recipes_for_returns_empty_when_no_domain_skills(tmp_path, monkeypatch):
    monkeypatch.setattr(helpers, "_skills_root", lambda: tmp_path)
    assert helpers.recipes_for("https://example.com") == []


def test_recipes_for_finds_exact_host(tmp_path, monkeypatch):
    skill_dir = tmp_path / "domain-skills" / "example.com"
    skill_dir.mkdir(parents=True)
    (skill_dir / "login.md").write_text("# login")
    (skill_dir / "cart.md").write_text("# cart")
    monkeypatch.setattr(helpers, "_skills_root", lambda: tmp_path)

    found = helpers.recipes_for("https://example.com/path")
    assert set(found) == {
        "domain-skills/example.com/login.md",
        "domain-skills/example.com/cart.md",
    }


def test_recipes_for_falls_back_to_second_level_domain(tmp_path, monkeypatch):
    skill_dir = tmp_path / "domain-skills" / "example.com"
    skill_dir.mkdir(parents=True)
    (skill_dir / "login.md").write_text("# login")
    monkeypatch.setattr(helpers, "_skills_root", lambda: tmp_path)

    found = helpers.recipes_for("https://mail.corp.example.com/")
    assert found == ["domain-skills/example.com/login.md"]


def test_recipes_for_strips_www(tmp_path, monkeypatch):
    skill_dir = tmp_path / "domain-skills" / "amazon.com"
    skill_dir.mkdir(parents=True)
    (skill_dir / "s.md").write_text("# search")
    monkeypatch.setattr(helpers, "_skills_root", lambda: tmp_path)

    found = helpers.recipes_for("https://www.amazon.com/")
    assert found == ["domain-skills/amazon.com/s.md"]


def test_recipes_for_handles_missing_host(tmp_path, monkeypatch):
    monkeypatch.setattr(helpers, "_skills_root", lambda: tmp_path)
    assert helpers.recipes_for("not-a-valid-url") == []


def test_recipe_banner_formats_when_matches(tmp_path, monkeypatch):
    skill_dir = tmp_path / "domain-skills" / "a.com"
    skill_dir.mkdir(parents=True)
    (skill_dir / "x.md").write_text("# x")
    monkeypatch.setattr(helpers, "_skills_root", lambda: tmp_path)

    banner = helpers.recipe_banner("https://a.com/y")
    assert "Recipes for a.com" in banner
    assert "domain-skills/a.com/x.md" in banner


def test_recipe_banner_empty_when_no_match(tmp_path, monkeypatch):
    monkeypatch.setattr(helpers, "_skills_root", lambda: tmp_path)
    assert helpers.recipe_banner("https://unknown.example") == ""


def _write_job_boards(tmp_path):
    skill_dir = tmp_path / "domain-skills" / "job-boards"
    skill_dir.mkdir(parents=True)
    (skill_dir / "indeed-glassdoor.md").write_text("---\nhosts: indeed.com, glassdoor.com\n---\n\n# Indeed")
    (skill_dir / "jobsdb-seek.md").write_text("---\nhosts: jobsdb.com, jobstreet.com, seek.com.au\n---\n\n# JobsDB")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://hk.indeed.com/jobs", "domain-skills/job-boards/indeed-glassdoor.md"),
        ("https://www.indeed.com/jobs", "domain-skills/job-boards/indeed-glassdoor.md"),
        ("https://www.glassdoor.com/", "domain-skills/job-boards/indeed-glassdoor.md"),
        ("https://hk.jobsdb.com/jobs", "domain-skills/job-boards/jobsdb-seek.md"),
        ("https://id.jobstreet.com/jobs", "domain-skills/job-boards/jobsdb-seek.md"),
        ("https://seek.com.au/", "domain-skills/job-boards/jobsdb-seek.md"),
    ],
)
def test_recipes_for_resolves_frontmatter_declared_hosts(tmp_path, monkeypatch, url, expected):
    _write_job_boards(tmp_path)
    monkeypatch.setattr(helpers, "_skills_root", lambda: tmp_path)
    assert helpers.recipes_for(url) == [expected]


def test_recipes_for_ignores_unrelated_frontmatter_host(tmp_path, monkeypatch):
    _write_job_boards(tmp_path)
    monkeypatch.setattr(helpers, "_skills_root", lambda: tmp_path)
    assert helpers.recipes_for("https://monster.com/") == []


def test_recipes_for_prefers_host_directory_over_frontmatter(tmp_path, monkeypatch):
    _write_job_boards(tmp_path)
    dir_recipe = tmp_path / "domain-skills" / "indeed.com"
    dir_recipe.mkdir(parents=True)
    (dir_recipe / "search.md").write_text("# search")
    monkeypatch.setattr(helpers, "_skills_root", lambda: tmp_path)
    assert helpers.recipes_for("https://indeed.com/") == ["domain-skills/indeed.com/search.md"]


# ── Keyboard primitives (BiDi input.performActions) ────────────


def _record(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(helpers, "bidi", lambda method, **params: calls.append((method, params)) or {})
    return calls


def test_special_keys_cover_navigation_keys():
    for k in ("Enter", "Tab", "Backspace", "Escape", "ArrowLeft", "ArrowRight"):
        assert k in helpers.SPECIAL_KEYS


def test_modifier_bits_unchanged():
    assert helpers.MODIFIER_BITS == {"Alt": 1, "Control": 2, "Meta": 4, "Shift": 8}


def test_press_key_special_maps_to_code_point(monkeypatch):
    calls = _record(monkeypatch)
    helpers.press_key("Enter")
    method, params = calls[0]
    assert method == "input.performActions"
    source = params["actions"][0]
    assert source["type"] == "key"
    values = [a["value"] for a in source["actions"]]
    assert "" in values  # WebDriver Enter code point


def test_press_key_single_char(monkeypatch):
    calls = _record(monkeypatch)
    helpers.press_key("a")
    actions = calls[0][1]["actions"][0]["actions"]
    assert [a["type"] for a in actions] == ["keyDown", "keyUp"]
    assert all(a["value"] == "a" for a in actions)


def test_press_key_modifier_list_wraps_key(monkeypatch):
    calls = _record(monkeypatch)
    helpers.press_key("a", modifiers=["Control", "Shift"])
    actions = calls[0][1]["actions"][0]["actions"]
    downs = [a["value"] for a in actions if a["type"] == "keyDown"]
    assert "" in downs  # Control
    assert "" in downs  # Shift
    assert "a" in downs


def test_press_key_bitfield_modifiers(monkeypatch):
    calls = _record(monkeypatch)
    helpers.press_key("a", modifiers=2 | 8)  # Control | Shift
    downs = [a["value"] for a in calls[0][1]["actions"][0]["actions"] if a["type"] == "keyDown"]
    assert "" in downs
    assert "" in downs


def test_press_key_unknown_modifier_ignored(monkeypatch):
    calls = _record(monkeypatch)
    helpers.press_key("a", modifiers=["NotAKey", "Control"])
    downs = [a["value"] for a in calls[0][1]["actions"][0]["actions"] if a["type"] == "keyDown"]
    assert "" in downs
    assert "a" in downs
    assert len(downs) == 2  # only Control modifier + the key


def test_type_text_emits_keydown_keyup_per_char(monkeypatch):
    calls = _record(monkeypatch)
    helpers.type_text("hi")
    actions = calls[0][1]["actions"][0]["actions"]
    assert [a["value"] for a in actions] == ["h", "h", "i", "i"]
    assert [a["type"] for a in actions] == ["keyDown", "keyUp", "keyDown", "keyUp"]


# ── Click / scroll primitives ──────────────────────────────────


def test_click_sends_pointer_move_down_up(monkeypatch):
    calls = _record(monkeypatch)
    helpers.click(100, 200, button="right", clicks=2)
    method, params = calls[0]
    assert method == "input.performActions"
    source = params["actions"][0]
    assert source["type"] == "pointer"
    actions = source["actions"]
    assert actions[0] == {"type": "pointerMove", "x": 100, "y": 200}
    downs = [a for a in actions if a["type"] == "pointerDown"]
    assert len(downs) == 2
    assert downs[0]["button"] == 2  # right


def test_scroll_uses_wheel_source(monkeypatch):
    calls = _record(monkeypatch)
    helpers.scroll(50, 50, dy=-100)
    source = calls[0][1]["actions"][0]
    assert source["type"] == "wheel"
    assert source["actions"][0]["deltaY"] == -100


# ── Ref resolution ─────────────────────────────────────────────


def test_click_ref_resolves_center(monkeypatch):
    monkeypatch.setattr(helpers, "_eval_value", lambda expr, context=None: {"found": True, "x": 12, "y": 34})
    calls = _record(monkeypatch)
    helpers.click_ref("e5")
    source = calls[0][1]["actions"][0]
    assert source["actions"][0] == {"type": "pointerMove", "x": 12, "y": 34}


def test_click_ref_unknown_raises(monkeypatch):
    monkeypatch.setattr(helpers, "_eval_value", lambda expr, context=None: {"found": False})
    with pytest.raises(RuntimeError, match="unknown ref"):
        helpers.click_ref("e99")


# ── JS evaluation unwrapping ───────────────────────────────────


def test_js_unwraps_json_string(monkeypatch):
    monkeypatch.setattr(
        helpers, "_eval", lambda expr, context=None, await_promise=True: {"type": "success", "result": {"type": "string", "value": '{"a":1}'}}
    )
    assert helpers.js("whatever") == {"a": 1}


def test_js_returns_none_for_undefined(monkeypatch):
    monkeypatch.setattr(helpers, "_eval", lambda *a, **k: {"type": "success", "result": {"type": "undefined"}})
    assert helpers.js("x") is None


def test_js_raises_on_exception(monkeypatch):
    monkeypatch.setattr(helpers, "_eval", lambda *a, **k: {"type": "exception", "exceptionDetails": {"text": "boom"}})
    with pytest.raises(RuntimeError, match="boom"):
        helpers.js("x")


# ── Screenshot format mapping ──────────────────────────────────


def test_screenshot_webp_maps_to_jpeg(monkeypatch, tmp_path):
    calls: list[tuple[str, dict]] = []
    payload = base64.b64encode(b"img").decode()
    monkeypatch.setattr(helpers, "bidi", lambda method, **params: calls.append((method, params)) or {"data": payload})
    helpers.screenshot(path=str(tmp_path / "s.webp"), image_format="webp", quality=50)
    fmt = calls[0][1]["format"]
    assert fmt["type"] == "image/jpeg"
    assert abs(fmt["quality"] - 0.5) < 1e-9


def test_screenshot_full_page_sets_document_origin(monkeypatch, tmp_path):
    calls: list[tuple[str, dict]] = []
    payload = base64.b64encode(b"img").decode()
    monkeypatch.setattr(helpers, "bidi", lambda method, **params: calls.append((method, params)) or {"data": payload})
    helpers.screenshot(path=str(tmp_path / "s.png"), full_page=True)
    assert calls[0][1]["origin"] == "document"


def test_screenshot_rejects_bad_format():
    with pytest.raises(ValueError, match="format must be"):
        helpers.screenshot(image_format="gif")
