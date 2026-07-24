"""The manifest is the hand-authored source of the catalog + new-agent defaults; the Python model
reads it for its field defaults. These lock the file's shape, that the model honors it, and the
union's credential-shape guarantees."""

import json

import pydantic as pyd
import pytest

from core.config import (
    MANIFEST_PATH,
    ClaudeConfig,
    KimiConfig,
    OpenAIConfig,
    OpenRouterConfig,
    VestaConfig,
    ZaiConfig,
    read_manifest,
    validate_config_updates,
    validate_provider_selection,
)


def _manifest():
    return json.loads(MANIFEST_PATH.read_text())


def test_manifest_has_both_providers_and_defaults():
    manifest = _manifest()
    assert read_manifest() == manifest  # typed runtime validation accepted the shipped contract
    assert manifest["default_provider"] == "claude"
    assert manifest["default_personality"] == "dry"
    assert sorted(manifest["providers"]) == ["claude", "kimi", "openai", "openrouter", "zai"]
    ordered = sorted(manifest["providers"], key=lambda kind: manifest["providers"][kind]["order"])
    assert ordered == ["claude", "openai", "zai", "kimi", "openrouter"]
    assert manifest["providers"]["claude"]["models"] == ["opus", "sonnet"]
    assert manifest["providers"]["claude"]["context"]["presets"]  # the picker's curated suggestions
    assert manifest["providers"]["openrouter"]["models"] == "live"  # free-form, fetched separately
    assert manifest["providers"]["zai"]["default_model"] == "glm-5.2"
    assert manifest["providers"]["kimi"]["default_model"] == "kimi-for-coding"
    assert manifest["providers"]["openai"]["default_model"] == "gpt-5.6-sol"
    assert manifest["providers"]["openai"]["auxiliary_model"] == "gpt-5.6-luna"


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


def test_openrouter_preserves_an_explicit_200k_cap():
    provider = OpenRouterConfig(model="vendor/model", key="key", max_context_tokens=200_000)
    assert provider.max_context_tokens == 200_000


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


@pytest.mark.parametrize(
    "provider_type,values",
    [
        (OpenRouterConfig, {"model": " ", "key": "key"}),
        (ZaiConfig, {"model": "glm-5.2", "key": " "}),
        (KimiConfig, {"model": " ", "key": "key"}),
        (OpenAIConfig, {"model": " "}),
    ],
)
def test_provider_models_and_keys_must_not_be_blank(provider_type, values):
    with pytest.raises(pyd.ValidationError):
        provider_type.model_validate(values)


@pytest.mark.parametrize(
    "provider_type,values",
    [
        (ZaiConfig, {"model": "made-up-glm", "key": "key"}),
        (KimiConfig, {"model": "made-up-kimi", "key": "key"}),
        (OpenAIConfig, {"model": "made-up-gpt"}),
    ],
)
def test_fixed_providers_reject_models_outside_the_manifest(provider_type, values):
    with pytest.raises(ValueError, match="is not a supported"):
        validate_provider_selection(provider_type.model_validate(values))


def test_persisted_fixed_model_load_is_lenient_for_catalog_rollout_compatibility():
    provider = ZaiConfig(model="previously-supported-glm", key="key")
    assert provider.model == "previously-supported-glm"


def test_reauth_preserves_a_persisted_model_removed_from_catalog(config):
    from core.config import update_config_store

    update_config_store({"provider": {"kind": "claude", "model": "retired-alias"}})
    current = VestaConfig()
    updates = validate_config_updates(current, {"provider": {"kind": "claude"}})
    assert updates["provider"] == {"kind": "claude", "model": "retired-alias"}


def test_subscription_contexts_are_model_specific():
    providers = _manifest()["providers"]
    assert providers["zai"]["context_by_model"]["glm-5.2"]["default"] == 1_000_000
    assert providers["zai"]["context"]["default"] == 200_000
    assert providers["kimi"]["context_by_model"]["k3"]["default"] == 262_144
    assert providers["kimi"]["context_by_model"]["k3"]["presets"][0]["tokens"] == 1_048_576
    assert providers["kimi"]["context"]["default"] == 262_144
    assert providers["openrouter"]["context"]["presets"] == []
    assert providers["openrouter"]["context"]["max"] is None
    for kind in ("zai", "kimi", "openai"):
        entry = providers[kind]
        policies = [entry["context"], *entry.get("context_by_model", {}).values()]
        for policy in policies:
            assert policy["max"] >= policy["default"]
            assert all(preset["tokens"] <= policy["max"] for preset in policy["presets"])


def test_subscription_configs_reject_context_beyond_the_selected_model():
    with pytest.raises(ValueError, match=r"glm-4\.7 supports at most 200000"):
        validate_config_updates(
            VestaConfig(),
            {"provider": {"kind": "zai", "model": "glm-4.7", "key": "key", "max_context_tokens": 1_000_000}},
        )
    with pytest.raises(ValueError, match="kimi-for-coding supports at most 262144"):
        validate_config_updates(
            VestaConfig(),
            {"provider": {"kind": "kimi", "model": "kimi-for-coding", "key": "key", "max_context_tokens": 1_048_576}},
        )


def test_claude_context_gates_large_windows_by_plan():
    # The 1M-context beta is a Max-only entitlement, so the picker maps plan -> default and marks the
    # >200K windows Max-only; the 200K window is offered to every plan.
    context = _manifest()["providers"]["claude"]["context"]
    assert context["defaults_by_plan"] == {"max": 1000000, "pro": 200000, "free": 200000}
    plans_by_tokens = {preset["tokens"]: preset["plans"] for preset in context["presets"] if "plans" in preset}
    assert plans_by_tokens == {1000000: ["max"], 500000: ["max"]}
    window_200k = next(preset for preset in context["presets"] if preset["tokens"] == 200000)
    assert "plans" not in window_200k
