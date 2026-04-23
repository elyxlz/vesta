"""Unit tests for helpers that don't require a live browser."""

from __future__ import annotations

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


# ── Keyboard primitives ────────────────────────────────────────


def test_special_keys_cover_navigation_keys():
    for k in ("Enter", "Tab", "Backspace", "Escape", "ArrowLeft", "ArrowRight"):
        assert k in helpers.SPECIAL_KEYS


def test_modifier_bits_are_cdp_spec():
    assert helpers.MODIFIER_BITS == {"Alt": 1, "Control": 2, "Meta": 4, "Shift": 8}


def test_press_key_special_dispatches_correct_events(monkeypatch):
    sent: list[tuple[str, dict]] = []

    def fake_cdp(method: str, session_id=None, **params):
        sent.append((method, params))
        return {}

    monkeypatch.setattr(helpers, "cdp", fake_cdp)

    helpers.press_key("Enter")
    types = [(m, p["type"]) for m, p in sent]
    assert ("Input.dispatchKeyEvent", "keyDown") in types
    assert ("Input.dispatchKeyEvent", "char") in types  # Enter has text '\r'
    assert ("Input.dispatchKeyEvent", "keyUp") in types

    key_up = [p for m, p in sent if p["type"] == "keyUp"][0]
    assert key_up["key"] == "Enter"
    assert key_up["windowsVirtualKeyCode"] == 13


def test_press_key_single_char_sends_char_event(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(helpers, "cdp", lambda method, session_id=None, **p: sent.append({"method": method, **p}) or {})

    helpers.press_key("a")

    chars = [s for s in sent if "type" in s and s["type"] == "char"]
    assert len(chars) == 1
    assert chars[0]["text"] == "a"


def test_press_key_modifier_list_converts_to_bits(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(helpers, "cdp", lambda method, session_id=None, **p: sent.append({"method": method, **p}) or {})

    helpers.press_key("a", modifiers=["Control", "Shift"])

    key_down = [s for s in sent if "type" in s and s["type"] == "keyDown"][0]
    assert key_down["modifiers"] == (2 | 8)


def test_press_key_unknown_modifier_ignored(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(helpers, "cdp", lambda method, session_id=None, **p: sent.append({"method": method, **p}) or {})

    helpers.press_key("a", modifiers=["NotARealKey", "Control"])

    key_down = [s for s in sent if "type" in s and s["type"] == "keyDown"][0]
    assert key_down["modifiers"] == 2  # Only Control survives.


# ── Click / scroll primitives ──────────────────────────────────


def test_click_sends_press_then_release(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(helpers, "cdp", lambda method, session_id=None, **p: calls.append((method, p)) or {})

    helpers.click(100, 200, button="right", clicks=2)

    assert len(calls) == 2
    assert calls[0][0] == "Input.dispatchMouseEvent"
    assert calls[0][1]["type"] == "mousePressed"
    assert calls[0][1]["button"] == "right"
    assert calls[0][1]["clickCount"] == 2
    assert calls[1][1]["type"] == "mouseReleased"


def test_scroll_uses_mouse_wheel(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(helpers, "cdp", lambda method, session_id=None, **p: calls.append({"method": method, **p}) or {})

    helpers.scroll(50, 50, dy=-100)
    assert calls[0]["method"] == "Input.dispatchMouseEvent"
    assert calls[0]["type"] == "mouseWheel"
    assert calls[0]["deltaY"] == -100
