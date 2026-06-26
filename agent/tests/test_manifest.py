"""The manifest is the hand-authored source of the catalog + new-agent defaults; the Python model
reads it for its field defaults. These lock the file's shape, that the model honors it, and the
union's credential-shape guarantees."""

import json

import pydantic as pyd
import pytest

from core.config import MANIFEST_PATH, ClaudeConfig, OpenRouterConfig, VestaConfig


def _manifest():
    return json.loads(MANIFEST_PATH.read_text())


def test_manifest_has_both_providers_and_defaults():
    manifest = _manifest()
    assert manifest["default_provider"] == "claude"
    assert manifest["default_personality"] == "dry"
    assert sorted(manifest["providers"]) == ["claude", "openrouter"]
    assert manifest["providers"]["claude"]["models"] == ["opus", "sonnet", "haiku"]
    assert manifest["providers"]["claude"]["context"]["presets"]  # the picker's curated suggestions
    assert manifest["providers"]["openrouter"]["models"] == "live"  # free-form, fetched separately


def test_model_defaults_come_from_the_manifest():
    # The single source: the model's field defaults are read from the manifest, not restated in code.
    manifest = _manifest()
    assert ClaudeConfig().model == manifest["providers"]["claude"]["default_model"]
    assert VestaConfig().agent_personality == manifest["default_personality"]


def test_openrouter_requires_a_key():
    # The union keeps the credential-shape invariant: openrouter without a key is unrepresentable.
    with pytest.raises(pyd.ValidationError):
        OpenRouterConfig.model_validate({"model": "some/model"})


def test_provider_shape_invariants():
    assert "key" not in ClaudeConfig.model_fields  # claude has no key
    assert "thinking" in ClaudeConfig.model_fields  # claude carries the thinking knob
    assert "thinking" not in OpenRouterConfig.model_fields  # openrouter can't set thinking
