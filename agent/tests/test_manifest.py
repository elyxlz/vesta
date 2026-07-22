"""The manifest is the hand-authored source of the catalog + new-agent defaults; the Python model
reads it for its field defaults. These lock the file's shape, that the model honors it, and the
union's credential-shape guarantees."""

import json

import pydantic as pyd
import pytest

from core.config import MANIFEST_PATH, ClaudeConfig, KimiConfig, OpenAIConfig, OpenRouterConfig, VestaConfig, ZaiConfig


def _manifest():
    return json.loads(MANIFEST_PATH.read_text())


def test_manifest_has_both_providers_and_defaults():
    manifest = _manifest()
    assert manifest["default_provider"] == "claude"
    assert manifest["default_personality"] == "dry"
    assert sorted(manifest["providers"]) == ["claude", "kimi", "openai", "openrouter", "zai"]
    assert manifest["providers"]["claude"]["models"] == ["opus", "sonnet"]
    assert manifest["providers"]["claude"]["context"]["presets"]  # the picker's curated suggestions
    assert manifest["providers"]["openrouter"]["models"] == "live"  # free-form, fetched separately
    assert manifest["providers"]["zai"]["default_model"] == "glm-5.2"
    assert manifest["providers"]["kimi"]["default_model"] == "kimi-for-coding"
    assert manifest["providers"]["openai"]["default_model"] == "gpt-5.6-sol"


def test_model_defaults_come_from_the_manifest():
    # The single source: the model's field defaults are read from the manifest, not restated in code.
    manifest = _manifest()
    assert ClaudeConfig().model == manifest["providers"]["claude"]["default_model"]
    assert VestaConfig().agent_personality == manifest["default_personality"]


def test_openrouter_requires_a_key():
    # The union keeps the credential-shape invariant: openrouter without a key is unrepresentable.
    with pytest.raises(pyd.ValidationError):
        OpenRouterConfig.model_validate({"model": "some/model"})


def test_openrouter_context_is_not_provider_capped_at_200k():
    provider = OpenRouterConfig(model="vendor/million-token-model", key="key", max_context_tokens=1_000_000)
    assert provider.max_context_tokens == 1_000_000


def test_zai_requires_a_key():
    with pytest.raises(pyd.ValidationError):
        ZaiConfig.model_validate({"model": "glm-4.7"})


def test_kimi_requires_a_key():
    with pytest.raises(pyd.ValidationError):
        KimiConfig.model_validate({"model": "kimi-for-coding"})


def test_provider_shape_invariants():
    assert "key" not in ClaudeConfig.model_fields  # claude has no key
    assert "thinking" in ClaudeConfig.model_fields  # claude carries the thinking knob
    assert "thinking" not in OpenRouterConfig.model_fields  # openrouter can't set thinking
    assert "thinking" not in ZaiConfig.model_fields  # Z.AI uses its endpoint's native reasoning
    assert "thinking" not in KimiConfig.model_fields  # Kimi uses its endpoint's native reasoning
    assert "key" not in OpenAIConfig.model_fields  # ChatGPT uses OAuth, never an API key


def test_subscription_contexts_are_model_specific():
    providers = _manifest()["providers"]
    assert providers["zai"]["context_by_model"]["glm-5.2"]["default"] == 1_000_000
    assert providers["zai"]["context_by_model"]["glm-4.7"]["default"] == 200_000
    assert providers["kimi"]["context_by_model"]["k3"]["default"] == 1_048_576
    assert providers["kimi"]["context_by_model"]["kimi-for-coding"]["default"] == 262_144
    assert providers["openrouter"]["context"]["presets"] == []


def test_subscription_configs_reject_context_beyond_the_selected_model():
    with pytest.raises(pyd.ValidationError, match=r"glm-4\.7 supports at most 200000"):
        ZaiConfig(model="glm-4.7", key="key", max_context_tokens=1_000_000)
    with pytest.raises(pyd.ValidationError, match="kimi-for-coding supports at most 262144"):
        KimiConfig(model="kimi-for-coding", key="key", max_context_tokens=1_048_576)


def test_claude_context_gates_large_windows_by_plan():
    # The 1M-context beta is a Max-only entitlement, so the picker maps plan -> default and marks the
    # >200K windows Max-only; the 200K window is offered to every plan.
    context = _manifest()["providers"]["claude"]["context"]
    assert context["defaults_by_plan"] == {"max": 1000000, "pro": 200000, "free": 200000}
    plans_by_tokens = {preset["tokens"]: preset["plans"] for preset in context["presets"] if "plans" in preset}
    assert plans_by_tokens == {1000000: ["max"], 500000: ["max"]}
    window_200k = next(preset for preset in context["presets"] if preset["tokens"] == 200000)
    assert "plans" not in window_200k
