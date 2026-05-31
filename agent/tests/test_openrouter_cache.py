"""Tests for the OpenRouter caching proxy's request transforms."""

import core.models as vm
from core.client import build_client_options
from core.openrouter_cache import _usage_int, transform_request


def _claude_code_body():
    """A request shaped like what claude-code sends on the OpenRouter path: a random
    cch billing header, real system content, tools, and moving message breakpoints."""
    return {
        "model": "deepseek/deepseek-v4-flash",
        "system": [
            {"type": "text", "text": "x-anthropic-billing-header: cc_version=2.1; cc_entrypoint=sdk-cli; cch=9af3e1;"},
            {"type": "text", "text": "You are a helpful assistant.", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "Long stable instructions " * 50, "cache_control": {"type": "ephemeral"}},
        ],
        "tools": [{"name": "Bash", "cache_control": {"type": "ephemeral"}}, {"name": "Read"}],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}]},
        ],
    }


def _count_cache_control(obj):
    if isinstance(obj, dict):
        return ("cache_control" in obj) + sum(_count_cache_control(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_count_cache_control(v) for v in obj)
    return 0


def test_transform_neutralizes_random_cch():
    body = _claude_code_body()
    out = transform_request(body, provider="Alibaba", session_id="s")
    assert "cch=stable;" in out["system"][0]["text"]
    assert "cch=9af3e1;" not in out["system"][0]["text"]


def test_transform_collapses_to_single_system_breakpoint():
    body = _claude_code_body()
    out = transform_request(body, provider="Alibaba", session_id="s")
    # Exactly one cache_control, on the last system block, with a 1h TTL.
    assert _count_cache_control(out) == 1
    assert out["system"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "cache_control" not in out["tools"][0]
    assert "cache_control" not in out["messages"][0]["content"][0]


def test_transform_injects_provider_and_session():
    body = _claude_code_body()
    out = transform_request(body, provider="DeepInfra", session_id="vesta-charbel")
    assert out["provider"] == {"order": ["DeepInfra"], "allow_fallbacks": True}
    assert out["session_id"] == "vesta-charbel"


def test_transform_is_passthrough_without_provider():
    body = _claude_code_body()
    before = dict(body)
    out = transform_request(body, provider=None, session_id="s")
    # Untouched: no provider injected, original breakpoints intact, cch unchanged.
    assert "provider" not in out
    assert out["system"][0]["text"] == before["system"][0]["text"]
    assert _count_cache_control(out) == _count_cache_control(before)


def test_transform_handles_missing_or_empty_system():
    assert transform_request({"model": "m"}, provider="Alibaba", session_id="s") == {"model": "m"}
    assert "provider" not in transform_request({"model": "m", "system": []}, provider="Alibaba", session_id="s")


def test_usage_int_parses_safely():
    assert _usage_int({"usage": {"input_tokens": 42}}, "input_tokens") == 42
    assert _usage_int({"usage": {"cache_read_input_tokens": 0}}, "cache_read_input_tokens") == 0
    assert _usage_int({}, "input_tokens") == 0
    assert _usage_int({"usage": {}}, "input_tokens") == 0
    assert _usage_int(None, "input_tokens") == 0


def _config_with_memory(tmp_path, **overrides):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent", **overrides)
    config.agent_dir.mkdir(parents=True, exist_ok=True)
    (config.agent_dir / "MEMORY.md").write_text("test memory")
    return config


def test_build_client_options_uses_proxy_url(tmp_path, state):
    config = _config_with_memory(tmp_path, agent_provider="openrouter", agent_model="deepseek/deepseek-v4-flash")
    state.openrouter_proxy_url = "http://127.0.0.1:54321"
    options = build_client_options(config, state)
    assert options.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:54321"


def test_build_client_options_requires_proxy_for_openrouter(tmp_path, state):
    import pytest

    config = _config_with_memory(tmp_path, agent_provider="openrouter", agent_model="deepseek/deepseek-v4-flash")
    with pytest.raises(RuntimeError):
        build_client_options(config, state)
