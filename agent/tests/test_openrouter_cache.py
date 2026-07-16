"""Tests for the OpenRouter caching proxy's request transforms."""

import asyncio
import json

from aiohttp import web

import core.config as cfg
from core.client import build_client_options
from core.openrouter_cache import (
    _CACHE_LOG_EVERY,
    _PrestreamError,
    _forward_bodies,
    _forward_with_retry,
    _record_cache_usage,
    _sniff_usage,
    _usage_int,
    transform_request,
)


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


def test_forward_bodies_retries_unpinned_when_provider_pinned():
    parsed = {"model": "m", "provider": {"order": ["Baidu"], "allow_fallbacks": True}, "messages": []}
    bodies = _forward_bodies(parsed, b"raw")
    assert len(bodies) == 2
    assert "provider" in json.loads(bodies[0])  # first attempt keeps the pin
    assert "provider" not in json.loads(bodies[1])  # retry drops it to route around a stall


def test_forward_bodies_single_attempt_when_unpinned():
    parsed = {"model": "m", "messages": []}
    assert _forward_bodies(parsed, b"raw") == [json.dumps(parsed).encode()]


def test_forward_bodies_passes_raw_through_when_unparsed():
    assert _forward_bodies(None, b"raw-bytes") == [b"raw-bytes"]


def test_forward_with_retry_falls_back_after_prestream_failure():
    tried: list[bytes] = []

    async def attempt(body: bytes) -> web.StreamResponse:
        tried.append(body)
        if len(tried) == 1:
            raise _PrestreamError("stalled")
        return web.Response(status=200, text="ok")

    resp = asyncio.run(_forward_with_retry([b"pinned", b"unpinned"], attempt))
    assert resp.status == 200
    assert tried == [b"pinned", b"unpinned"]  # retried the second body


def test_forward_with_retry_returns_504_when_every_attempt_fails():
    async def attempt(body: bytes) -> web.StreamResponse:
        raise _PrestreamError("stalled")

    resp = asyncio.run(_forward_with_retry([b"a", b"b"], attempt))
    assert resp.status == 504


def test_forward_with_retry_does_not_retry_on_first_success():
    tried: list[bytes] = []

    async def attempt(body: bytes) -> web.StreamResponse:
        tried.append(body)
        return web.Response(status=200)

    resp = asyncio.run(_forward_with_retry([b"a", b"b"], attempt))
    assert resp.status == 200
    assert tried == [b"a"]  # first attempt streamed; no retry


def test_sniff_usage_extracts_both_fields():
    # final message_delta-style chunk carries both counters
    chunk = b'data: {"type":"message_delta","usage":{"input_tokens":152,"output_tokens":9,"cache_read_input_tokens":21632}}'
    assert _sniff_usage(chunk) == (152, 21632)


def test_sniff_usage_returns_none_when_a_field_is_missing():
    assert _sniff_usage(b'{"usage":{"output_tokens":9,"cache_read_input_tokens":21632}}') is None
    assert _sniff_usage(b'{"usage":{"input_tokens":152}}') is None


def _stats_app(providers):
    from aiohttp import web

    app = web.Application()
    app["cache_stats"] = {"n": 0, "input": 0, "cache_read": 0}
    app["providers"] = providers
    return app


def test_record_cache_usage_windows_and_resets():
    app = _stats_app({"m": "Alibaba"})
    for _ in range(_CACHE_LOG_EVERY - 1):
        _record_cache_usage(app, 1000, 900)
    assert app["cache_stats"]["n"] == _CACHE_LOG_EVERY - 1  # not yet flushed
    _record_cache_usage(app, 1000, 900)
    assert app["cache_stats"] == {"n": 0, "input": 0, "cache_read": 0}  # window flushed + reset


def test_record_cache_usage_handles_zero_input_window():
    # all cold writes (input 0) must not divide-by-zero at the flush boundary
    app = _stats_app({"m": None})
    for _ in range(_CACHE_LOG_EVERY):
        _record_cache_usage(app, 0, 0)
    assert app["cache_stats"]["n"] == 0


def test_usage_int_parses_safely():
    assert _usage_int({"usage": {"input_tokens": 42}}, "input_tokens") == 42
    assert _usage_int({"usage": {"cache_read_input_tokens": 0}}, "cache_read_input_tokens") == 0
    assert _usage_int({}, "input_tokens") == 0
    assert _usage_int({"usage": {}}, "input_tokens") == 0
    assert _usage_int(None, "input_tokens") == 0


def _config_with_memory(tmp_path, **overrides):
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent", **overrides)
    config.agent_dir.mkdir(parents=True, exist_ok=True)
    (config.agent_dir / "MEMORY.md").write_text("test memory")
    return config


_OPENROUTER = {"kind": "openrouter", "model": "deepseek/deepseek-v4-flash", "key": "sk-or-test"}


def test_build_client_options_uses_proxy_url(tmp_path, state):
    config = _config_with_memory(tmp_path, provider=_OPENROUTER)
    state.openrouter_proxy_url = "http://127.0.0.1:54321"
    options = build_client_options(config, state)
    assert options.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:54321"


def test_build_client_options_requires_proxy_for_openrouter(tmp_path, state):
    import pytest

    config = _config_with_memory(tmp_path, provider=_OPENROUTER)
    with pytest.raises(RuntimeError):
        build_client_options(config, state)
