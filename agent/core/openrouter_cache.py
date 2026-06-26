"""Local caching proxy for the OpenRouter provider path.

The Claude Agent SDK, talking to OpenRouter's Anthropic endpoint, never lands
prompt-cache hits for three independent reasons (each isolated empirically):

  1. claude-code prepends a per-request RANDOM billing header as the first system
     block (`x-anthropic-billing-header: ...; cch=<random>;`). The random `cch`
     sits at the very front of the prompt and busts the cache prefix every call.
  2. OpenRouter load-balances the model across upstream providers whose caching
     differs wildly (some prefix-cache, some only on byte-identical replays, some
     not at all), so by default hits scatter and the cache never warms.
  3. With multiple cache_control breakpoints OpenRouter effectively honors only the
     last one, which claude-code puts on the moving final message, so the cached
     prefix shifts every turn.

This proxy sits between the SDK subprocess and OpenRouter (the SDK's
ANTHROPIC_BASE_URL points here) and rewrites each /v1/messages request to fix all
three: neutralize `cch`, pin the cheapest provider that *verifiably* prefix-caches
the model (probed at boot), and place one stable 1h breakpoint on the last system
block (the whole growing prefix then caches via the providers' longest-prefix
matching). `allow_fallbacks` keeps the agent alive (uncached) if the pinned
provider is momentarily unavailable. The proxy is the single, always-on request
path for the OpenRouter provider; the SDK never talks to OpenRouter directly.
"""

import asyncio
import json
import re
import socket
import typing as tp

import aiohttp
from aiohttp import web

from . import logger
from .config import OpenRouterConfig, VestaConfig
from .models import State
from .provider import OPENROUTER_SMALL_FAST_MODEL
from .provider import TERMINAL_PROVIDER_ERRORS, observed_provider_failure

OPENROUTER_API = "https://openrouter.ai/api"
_ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/{model}/endpoints"
_MESSAGES_URL = "https://openrouter.ai/api/v1/messages"
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)
# The forwarding session must NOT cap a streamed LLM response by total time — a single agent
# turn legitimately runs minutes. Bound the connect and the idle gap between chunks instead, so
# only a genuinely stalled upstream (no bytes for this long) is cut. aiohttp's default would
# otherwise impose a 300s total cap, which silently killed long/slow OpenRouter turns.
_FORWARD_TIMEOUT = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=180)
_MAX_PROBE_CANDIDATES = 4
_MIN_CACHE_FRACTION = 0.5  # warm call must read back at least half the prefix to count as caching
_CACHE_TTL = "1h"  # survive the idle gaps typical of a personal assistant (default is 5 min)
_SHUTDOWN_TIMEOUT = 5.0  # bound proxy drain on shutdown (matches the WS server's shutdown timeout)
_HOP_BY_HOP = ("content-length", "content-encoding", "transfer-encoding", "connection")
_PROBE_SYSTEM = ("You are a helpful assistant who answers concisely. " * 40 + "\n") * 20
_CACHE_LOG_EVERY = 50  # summarize the hit rate once per this many model requests
_LOW_CACHE_FRACTION = 0.2  # below this over a window (with a provider verified) => warn caching is broken
_RE_INPUT_TOKENS = re.compile(rb'"input_tokens":(\d+)')
_RE_CACHE_READ = re.compile(rb'"cache_read_input_tokens":(\d+)')


# --- pure request transforms (unit-tested) ---


def _strip_cache_control(obj: tp.Any) -> None:
    if isinstance(obj, dict):
        block = tp.cast("dict[str, tp.Any]", obj)
        block.pop("cache_control", None)
        for value in block.values():
            _strip_cache_control(value)
    elif isinstance(obj, list):
        for value in tp.cast("list[tp.Any]", obj):
            _strip_cache_control(value)


def _neutralize_cch(system: list[tp.Any]) -> None:
    """Pin claude-code's random `cch=<random>;` billing token to a constant so the
    cached prefix is byte-stable across requests."""
    for block in system:
        if not isinstance(block, dict):
            continue
        text = block["text"] if "text" in block else ""
        if isinstance(text, str) and text.startswith("x-anthropic-billing-header"):
            block["text"] = re.sub(r"cch=[^;]*;", "cch=stable;", text)


def transform_request(parsed: dict[str, tp.Any], *, provider: str | None, session_id: str) -> dict[str, tp.Any]:
    """Rewrite an Anthropic /v1/messages body for cache hits on OpenRouter. Mutates
    and returns `parsed`. With no verified caching provider it is a no-op passthrough."""
    if not provider:
        return parsed
    system = parsed["system"] if "system" in parsed else None
    if not isinstance(system, list) or not system:
        return parsed
    _neutralize_cch(system)
    tools = parsed["tools"] if "tools" in parsed else []
    for tool in tools:
        _strip_cache_control(tool)
    _strip_cache_control(parsed["messages"] if "messages" in parsed else [])
    for block in system:
        _strip_cache_control(block)
    last = system[-1]
    if isinstance(last, dict):
        last["cache_control"] = {"type": "ephemeral", "ttl": _CACHE_TTL}
    parsed["provider"] = {"order": [provider], "allow_fallbacks": True}
    parsed["session_id"] = session_id
    return parsed


# --- provider resolution (cheapest verified-caching upstream, probed at boot) ---


def _usage_int(payload: tp.Any, key: str) -> int:
    """Read an int counter out of an OpenRouter response's `usage` block, 0 if absent."""
    if not isinstance(payload, dict) or "usage" not in payload:
        return 0
    usage = tp.cast("dict[str, tp.Any]", payload)["usage"]
    if isinstance(usage, dict) and key in usage:
        value = tp.cast("dict[str, tp.Any]", usage)[key]
        if isinstance(value, int):
            return value
    return 0


async def _cache_capable_providers(session: aiohttp.ClientSession, model: str, key: str) -> list[str]:
    """Provider names that bill an input_cache_read price for `model`, cheapest base
    price first, de-duplicated."""
    async with session.get(_ENDPOINTS_URL.format(model=model), headers={"Authorization": f"Bearer {key}"}, timeout=_HTTP_TIMEOUT) as resp:
        if resp.status != 200:
            return []
        body: tp.Any = await resp.json()
    if "data" not in body or "endpoints" not in body["data"]:
        return []
    priced: list[tuple[float, str]] = []
    for endpoint in body["data"]["endpoints"]:
        pricing = endpoint["pricing"] if "pricing" in endpoint else {}
        if "input_cache_read" not in pricing or "prompt" not in pricing or "provider_name" not in endpoint:
            continue
        if pricing["input_cache_read"] in (None, "", "0"):
            continue
        priced.append((float(pricing["prompt"]), str(endpoint["provider_name"])))
    priced.sort(key=lambda item: item[0])
    ordered: list[str] = []
    for _, name in priced:
        if name not in ordered:
            ordered.append(name)
    return ordered


async def _probe_caches(session: aiohttp.ClientSession, model: str, key: str, provider: str) -> bool:
    """True if `provider` prefix-caches `model`: a cold then a grown request pinned to
    it, where the grown call must read back most of the stable prefix."""

    def probe_body(grown: bool) -> dict[str, object]:
        messages: list[dict[str, object]] = [{"role": "user", "content": "Reply with: ok"}]
        if grown:
            messages += [{"role": "assistant", "content": "ok"}, {"role": "user", "content": "Reply with: ok again"}]
        return {
            "model": model,
            "max_tokens": 4,
            "provider": {"order": [provider], "allow_fallbacks": False},
            "system": [{"type": "text", "text": _PROBE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            "messages": messages,
        }

    async def call(grown: bool) -> object:
        async with session.post(
            _MESSAGES_URL, json=probe_body(grown), headers={"Authorization": f"Bearer {key}"}, timeout=_HTTP_TIMEOUT
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.json()

    cold = await call(False)
    cold_input = _usage_int(cold, "input_tokens")
    if cold_input == 0:
        return False
    grown = await call(True)
    cache_read = _usage_int(grown, "cache_read_input_tokens")
    return cache_read >= _MIN_CACHE_FRACTION * cold_input


_PROBE_ERRORS = (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError)


async def _resolve_provider(session: aiohttp.ClientSession, model: str, key: str) -> str | None:
    """Cheapest provider that verifiably prefix-caches `model`, or None (uncached).

    A transient failure probing one candidate must not abandon the rest, so each
    candidate is guarded independently; a malformed OpenRouter response (TypeError)
    is caught too rather than escaping into start_cache_proxy."""
    try:
        candidates = await _cache_capable_providers(session, model, key)
    except _PROBE_ERRORS as e:
        logger.warning(f"OpenRouter endpoint lookup failed for {model}: {e}")
        return None
    for candidate in candidates[:_MAX_PROBE_CANDIDATES]:
        try:
            verified = await _probe_caches(session, model, key, candidate)
        except _PROBE_ERRORS as e:
            logger.warning(f"OpenRouter cache probe of {candidate} for {model} failed: {e}")
            continue
        if verified:
            logger.startup(f"OpenRouter caching: {model} -> {candidate} (verified)")
            return candidate
    logger.warning(f"OpenRouter caching: no verified caching provider for {model}; running uncached")
    return None


# --- the proxy ---


class _PrestreamError(Exception):
    """An upstream forward that failed BEFORE any downstream bytes were sent, so the
    request can be safely retried (e.g. with the provider pin dropped)."""


_FORWARD_ERRORS = (TimeoutError, aiohttp.ClientError)


def _forward_bodies(parsed: dict[str, tp.Any] | None, raw: bytes) -> list[bytes]:
    """The upstream bodies to try, in order. For a transformed /v1/messages request that
    pinned a provider, append one retry with the pin removed: a pinned provider that stalls
    sends no error, so OpenRouter's own `allow_fallbacks` never fires — dropping the pin
    lets it route around the stalled upstream. Other requests forward `raw` unchanged."""
    if parsed is None:
        return [raw]
    bodies = [json.dumps(parsed).encode()]
    if "provider" in parsed:
        unpinned = {k: v for k, v in parsed.items() if k != "provider"}
        bodies.append(json.dumps(unpinned).encode())
    return bodies


def _gateway_error_response() -> web.Response:
    """A clean 504 the SDK can back off on, instead of the opaque 500 an uncaught handler
    exception produced when every upstream attempt failed."""
    return web.json_response(
        {"type": "error", "error": {"type": "api_error", "message": "openrouter upstream unavailable"}},
        status=504,
    )


async def _forward_with_retry(bodies: list[bytes], attempt: tp.Callable[[bytes], tp.Awaitable[web.StreamResponse]]) -> web.StreamResponse:
    """Try each body via `attempt`; return the first response that starts streaming. Every
    attempt failing before streaming yields a 504. A mid-stream failure is NOT retried (the
    response already started) — `attempt` returns the truncated response rather than raising."""
    last_error: Exception | None = None
    for body in bodies:
        try:
            return await attempt(body)
        except _PrestreamError as e:
            last_error = e
            logger.warning(f"OpenRouter forward failed before streaming; retrying if possible: {e}")
    logger.error(f"OpenRouter forward failed on all {len(bodies)} attempt(s): {last_error}")
    return _gateway_error_response()


async def _stream_upstream(
    request: web.Request, client: aiohttp.ClientSession, url: str, headers: dict[str, str], body: bytes, *, sniff: bool
) -> web.StreamResponse:
    """Forward one request upstream and stream the response back. Raises _PrestreamError if
    the upstream fails before the downstream response is prepared (retryable: stalled connect
    or no response headers within sock_read); a failure mid-stream ends the truncated response
    so the SDK retries on the broken stream."""
    response: web.StreamResponse | None = None
    try:
        async with client.request(request.method, url, data=body, headers=headers) as upstream:
            if upstream.status in TERMINAL_PROVIDER_ERRORS:
                state: State = request.app["state"]
                state.provider_status = observed_provider_failure(state.provider_status)
            # Forward upstream headers (Content-Type, Retry-After, rate-limit, ...) so the SDK
            # keeps its backoff signals. aiohttp already decompressed the body and StreamResponse
            # re-frames length/encoding, so drop those hop-by-hop headers.
            resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP}
            response = web.StreamResponse(status=upstream.status, headers=resp_headers)
            await response.prepare(request)
            sample: tuple[int, int] | None = None
            async for chunk in upstream.content.iter_any():
                if sniff and b"cache_read_input_tokens" in chunk:
                    found = _sniff_usage(chunk)
                    if found is not None:
                        sample = found  # keep the last (final message_delta) usage
                await response.write(chunk)
            await response.write_eof()
            if sample is not None:
                _record_cache_usage(request.app, *sample)
            return response
    except _FORWARD_ERRORS as e:
        if response is not None:
            # Already streaming downstream — can't retry or rewrite the status; end the
            # truncated response so the SDK sees a broken stream and retries upstream.
            logger.warning(f"OpenRouter stream interrupted mid-response: {e}")
            await response.write_eof()
            return response
        raise _PrestreamError(str(e)) from e


async def _handle(request: web.Request) -> web.StreamResponse:
    raw = await request.read()
    is_messages = request.path.endswith("/v1/messages")
    parsed: dict[str, tp.Any] | None = None
    if is_messages and raw:
        try:
            body_json: tp.Any = json.loads(raw)
            model = body_json["model"] if "model" in body_json else None
            providers = request.app["providers"]
            provider = providers[model] if model in providers else None
            parsed = transform_request(body_json, provider=provider, session_id=request.app["session_id"])
        except (json.JSONDecodeError, ValueError):
            parsed = None
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length", "transfer-encoding")}
    client: aiohttp.ClientSession = request.app["client"]
    url = OPENROUTER_API + request.raw_path
    bodies = _forward_bodies(parsed, raw)
    return await _forward_with_retry(bodies, lambda body: _stream_upstream(request, client, url, headers, body, sniff=is_messages))


def _sniff_usage(chunk: bytes) -> tuple[int, int] | None:
    """Extract (input_tokens, cache_read_input_tokens) from a response chunk if both
    are present, else None. Cheap: only runs when the chunk already contains the marker."""
    mi = _RE_INPUT_TOKENS.search(chunk)
    mc = _RE_CACHE_READ.search(chunk)
    if mi is None or mc is None:
        return None
    return int(mi.group(1)), int(mc.group(1))


def _record_cache_usage(app: web.Application, input_tokens: int, cache_read: int) -> None:
    """Accumulate cache stats and, once per window, log the hit rate (or warn if a
    provider was verified but hits collapsed — i.e. caching silently broke).

    Safe without a lock: the read-modify-write below has no await, so it is atomic on
    the single-threaded event loop."""
    stats = app["cache_stats"]
    stats["n"] += 1
    stats["input"] += input_tokens
    stats["cache_read"] += cache_read
    if stats["n"] < _CACHE_LOG_EVERY:
        return
    fraction = stats["cache_read"] / stats["input"] if stats["input"] else 0.0
    summary = f"OpenRouter cache: {stats['n']} requests, {fraction:.0%} of input tokens served from cache"
    if any(app["providers"].values()) and fraction < _LOW_CACHE_FRACTION:
        logger.warning(f"{summary} — caching may be broken (a provider was verified but hits are near zero)")
    else:
        logger.usage(summary)
    stats["n"] = stats["input"] = stats["cache_read"] = 0


async def _close_client(app: web.Application) -> None:
    await app["client"].close()


async def start_cache_proxy(config: VestaConfig, state: State) -> None:
    """Start the local OpenRouter caching proxy and set state.openrouter_proxy_url.

    The proxy is the single, always-on request path for the OpenRouter provider: the
    SDK's ANTHROPIC_BASE_URL points here, never at OpenRouter directly. Provider
    resolution is best-effort — a model with no verified caching provider (or no key
    to probe with) simply passes through uncached, but the proxy still runs."""
    # Default the session to the streaming-friendly forward timeout; the boot probes below
    # pass their own short _HTTP_TIMEOUT explicitly, so only the forwarding path inherits it.
    client = aiohttp.ClientSession(timeout=_FORWARD_TIMEOUT)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    started = False
    try:
        providers: dict[str, str | None] = {}
        if isinstance(config.provider, OpenRouterConfig):
            key = config.provider.key.get_secret_value()
            models = [config.provider.model]
            if OPENROUTER_SMALL_FAST_MODEL not in models:
                models.append(OPENROUTER_SMALL_FAST_MODEL)
            # Probe models concurrently so boot isn't serialized across them.
            resolved = await asyncio.gather(*(_resolve_provider(client, model, key) for model in models))
            providers = dict(zip(models, resolved))

        app = web.Application()
        app["providers"] = providers
        app["session_id"] = f"vesta-{config.agent_name}"
        app["client"] = client
        app["state"] = state
        app["config"] = config
        app["cache_stats"] = {"n": 0, "input": 0, "cache_read": 0}
        app.on_cleanup.append(_close_client)
        app.router.add_route("*", "/{tail:.*}", _handle)

        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        runner = web.AppRunner(app, shutdown_timeout=_SHUTDOWN_TIMEOUT)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        started = True
    finally:
        if not started:
            # Bring-up failed partway: close the session + listen socket so we don't
            # leak them on the crash/restart that an unset proxy URL will trigger.
            sock.close()
            await client.close()

    state.cache_proxy_runner = runner
    state.openrouter_proxy_url = f"http://127.0.0.1:{port}"
    logger.startup(f"OpenRouter cache proxy listening on {state.openrouter_proxy_url}")
