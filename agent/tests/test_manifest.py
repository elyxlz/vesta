"""The manifest is generated from the provider models; these lock it to the union and to the
committed JSON, and assert the union's type-level guarantees."""

import json

import pydantic as pyd
import pytest

from core.config import (
    MANIFEST_PATH,
    ClaudeConfig,
    Manifest,
    OpenRouterConfig,
    _PROVIDER_CLASSES,
    build_manifest,
)


def test_every_union_member_is_in_the_manifest():
    manifest = build_manifest()
    union_kinds = {cls.model_fields["kind"].default for cls in _PROVIDER_CLASSES}
    assert set(manifest.providers) == union_kinds


def test_every_provider_class_has_presentation_classvars():
    for cls in _PROVIDER_CLASSES:
        assert isinstance(cls.display, str) and cls.display
        assert cls.context_presets and cls.context_presets[0].tokens > 0


def test_manifest_entry_is_derived_from_the_model():
    manifest = build_manifest()
    claude = manifest.providers["claude"]
    assert claude.models == ["opus", "sonnet", "haiku"]  # from the Literal
    assert claude.default_model == "opus"  # from the field default
    assert claude.thinking_supported is True  # claude has a thinking field
    assert claude.context.default == 1_000_000  # first preset
    openrouter = manifest.providers["openrouter"]
    assert openrouter.models == "live"  # free-form str -> fetched live
    assert openrouter.thinking_supported is False  # openrouter has no thinking field
    assert openrouter.context.default == 200_000


def test_manifest_covers_whole_config_generically_and_folds_personalities():
    manifest = build_manifest()
    # prefs are derived from every scalar field, not a hand-picked subset.
    assert {"agent_personality", "timezone", "seed_context", "response_timeout"} <= set(manifest.prefs)
    assert manifest.prefs["agent_personality"] == "dry"
    # the personality catalog is folded in (no separate /personalities), sorted by declared order.
    names = [p.name for p in manifest.personalities]
    assert "dry" in names and names[0] == "dry"


def test_committed_manifest_is_fresh():
    """The committed manifest.json must match what the models generate (CI enforces this too)."""
    on_disk = Manifest.model_validate(json.loads(MANIFEST_PATH.read_text()))
    assert on_disk == build_manifest()


def test_openrouter_requires_a_key():
    # The union makes "openrouter without a key" structurally unrepresentable.
    with pytest.raises(pyd.ValidationError):
        OpenRouterConfig.model_validate({"model": "some/model"})


def test_claude_has_no_key_field():
    assert "key" not in ClaudeConfig.model_fields
    assert "thinking" in ClaudeConfig.model_fields
    assert "thinking" not in OpenRouterConfig.model_fields
