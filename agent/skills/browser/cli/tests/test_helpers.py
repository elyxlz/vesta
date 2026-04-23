"""Unit tests for helpers that don't require a live browser."""

from __future__ import annotations

from vesta_browser import helpers


def test_recipes_for_returns_empty_when_no_domain_skills(tmp_path, monkeypatch):
    # Point the skills root somewhere without domain-skills/.
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
