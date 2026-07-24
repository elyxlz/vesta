"""Per-agent LLM-provider auth (Claude OAuth or OpenRouter key). The provider choice and OpenRouter
key live in the config store; the Claude OAuth blob lives in `.credentials.json` (the `claude` CLI
reads it). On-disk state is the single source of truth: status is re-derived from disk on every boot,
and a runtime auth failure is an in-memory flip only (no separate persisted auth flag)."""

import dataclasses as dc
import enum
import json
import pathlib as pl
import time
import typing as tp

import aiohttp
import pydantic as pyd

from . import logger
from .config import CREDENTIALS_PATH, ClaudeOAuth, OpenRouterConfig, VestaConfig, merge_provider, read_claude_oauth, update_config_store

CLAUDE_JSON_PATH = pl.Path.home() / ".claude.json"

ANTHROPIC_API_URL = "https://api.anthropic.com"
OAUTH_BETA_HEADER = "oauth-2025-04-20"
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
_USAGE_TIMEOUT_S = 10
_USAGE_USER_AGENT = "claude-code/2.1.92"

# Cheap model the SDK uses for background work (compaction probes, etc.); pinned so an expensive
# primary model doesn't inflate background spend.
OPENROUTER_SMALL_FAST_MODEL = "anthropic/claude-haiku-4.5"


class ProviderAuthState(enum.StrEnum):
    AUTHENTICATED = "authenticated"
    NOT_AUTHENTICATED = "not_authenticated"


ProviderKind = tp.Literal["claude", "openrouter", "none"]
RATE_LIMIT_RETRY_FALLBACK_SECONDS = 300

# What counts as a terminal provider error — the credential is rejected (401) or the account can't
# pay (402) — owned here for every provider's reactive detector. Transient errors (5xx, 429 rate
# limit) are deliberately excluded: those resolve on retry and must not flip the agent to
# unauthenticated. OpenRouter sees it as an HTTP status (its cache proxy); Claude sees it as the
# Claude Agent SDK's classified error on the assistant turn. Two transports, one definition.
TERMINAL_PROVIDER_ERRORS = (401, 402)
# The Claude Agent SDK's AssistantMessage.error values that mean re-auth: 401 and 402.
_TERMINAL_AUTH_ERRORS = frozenset({"authentication_failed", "billing_error"})


def is_terminal_auth_error(error: str | None) -> bool:
    """The single decision for the Claude path: does this assistant turn represent a terminal
    auth/billing failure (401/402) requiring re-auth? The Claude Agent SDK classifies the upstream
    error directly on the AssistantMessage, so authentication_failed (401) and billing_error (402)
    are the terminal cases. A normal turn carries error=None and can never flip the agent to
    unauthenticated; transient errors (rate_limit, server_error) return False, so the CLI's own
    retries still fix them."""
    return error in _TERMINAL_AUTH_ERRORS


def is_unauthenticated(status: "ProviderStatus | None") -> bool:
    """The "dead token" predicate: gates handing prompts to the CLI (the processor's deferral
    and send_preempt) so a known-bad credential doesn't burn the CLI's retry budget."""
    return status is not None and status.state == ProviderAuthState.NOT_AUTHENTICATED


@dc.dataclass
class ProviderStatus:
    state: ProviderAuthState
    kind: ProviderKind
    model: str | None

    def __post_init__(self) -> None:
        # The model is only meaningful for an authenticated provider; an agent whose credentials are
        # missing or invalidated (boot derive or a runtime 401/402 flip) isn't using any model, so it
        # reports none. Enforced here so every construction path — including dc.replace — converges.
        if self.state != ProviderAuthState.AUTHENTICATED:
            self.model = None


class ProviderCooldown(pyd.BaseModel):
    reason: tp.Literal["rate_limit"] = "rate_limit"
    until: int
    window: str | None = None


def active_cooldown(cooldown: ProviderCooldown | None, *, now: float | None = None) -> ProviderCooldown | None:
    if cooldown is None:
        return None
    timestamp = time.time() if now is None else now
    return cooldown if cooldown.until > timestamp else None


def rate_limit_cooldown(*, resets_at: int | None, window: str | None, now: float | None = None) -> ProviderCooldown:
    timestamp = time.time() if now is None else now
    until = resets_at if resets_at is not None and resets_at > timestamp else int(timestamp) + RATE_LIMIT_RETRY_FALLBACK_SECONDS
    return ProviderCooldown(until=until, window=window)


def derive_status(config: VestaConfig) -> ProviderStatus:
    """Re-derive provider status at boot, purely from disk: the config store (provider + key) and
    `.credentials.json`. On-disk state is the single source of truth — a runtime auth failure is an
    in-memory flip only (see observed_provider_failure), so boot is always an honest reading of what's
    actually provisioned. Model comes from the config store via VestaConfig."""
    kind, authed = _derive_kind_and_auth(config)
    state = ProviderAuthState.AUTHENTICATED if authed else ProviderAuthState.NOT_AUTHENTICATED
    model = config.provider.model if config.provider is not None else None
    return ProviderStatus(state=state, kind=kind, model=model)


def _sign_in(kind: str, *, model: str | None, max_context_tokens: int | None, key: str | None, config: VestaConfig) -> str | None:
    """Build a provider patch, merge it into the store (shared merge: same-kind keeps the rest, a kind
    switch replaces), persist it, and return the resulting model for the status."""
    patch: dict[str, pyd.JsonValue] = {"kind": kind}
    if model is not None:
        patch["model"] = model
    if max_context_tokens is not None:
        patch["max_context_tokens"] = max_context_tokens
    if key is not None:
        patch["key"] = key
    merged = merge_provider(config, patch)
    update_config_store({"provider": merged})
    return merged["model"] if "model" in merged and isinstance(merged["model"], str) else None


def set_claude(credentials_json: str, model: str | None, max_context_tokens: int | None, *, config: VestaConfig) -> ProviderStatus:
    """Write the Claude OAuth credentials to the SDK path and merge a claude provider patch into the
    store (model/context unspecified on re-auth are preserved). The OAuth blob lives in the credentials
    file, never the store."""
    # Validate JSON shape before touching disk so we don't half-apply on bad input.
    json.loads(credentials_json)
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(credentials_json)
    CLAUDE_JSON_PATH.write_text('{"hasCompletedOnboarding":true}')
    reported = _sign_in("claude", model=model, max_context_tokens=max_context_tokens, key=None, config=config)
    logger.startup("Provider set to claude")
    return ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model=reported)


def set_openrouter(key: str, model: str, max_context_tokens: int | None, *, config: VestaConfig) -> ProviderStatus:
    """Merge the nested OpenRouter provider (key + model, plus any context chosen at sign-in) into the
    store. Vestad restarts the agent to apply it."""
    reported = _sign_in("openrouter", model=model, max_context_tokens=max_context_tokens, key=key, config=config)
    logger.startup(f"Provider set to openrouter model={model}")
    return ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="openrouter", model=reported)


def clear_provider() -> ProviderStatus:
    """Sign out: remove the Claude OAuth blob and clear the stored provider to None (no provider
    chosen), leaving the agent unprovisioned. General config (personality, timezone, ...) survives.
    Vestad restarts the agent."""
    CREDENTIALS_PATH.unlink(missing_ok=True)
    update_config_store({"provider": None})
    logger.startup("Provider cleared (signed out)")
    return ProviderStatus(state=ProviderAuthState.NOT_AUTHENTICATED, kind="none", model=None)


def observed_provider_failure(status: ProviderStatus | None) -> ProviderStatus | None:
    """Called by the SDK response-stream handler on a terminal upstream auth/billing error (401
    invalid auth, 402 insufficient credits). Returns the status flipped to NOT_AUTHENTICATED, or the
    input unchanged when there's nothing to flip. The flip is in-memory only: on the next boot the
    agent re-derives from disk (creds present => authenticated), so a transient 402 that the user
    fixes by topping up credits recovers without a manual reconnect, and a genuinely dead credential
    just re-flips on its first failed call."""
    if status is None or status.state == ProviderAuthState.NOT_AUTHENTICATED:
        return status
    new_status = dc.replace(status, state=ProviderAuthState.NOT_AUTHENTICATED)
    logger.error(f"Provider {new_status.kind} flipped to not_authenticated (upstream auth/billing error)")
    return new_status


def _derive_kind_and_auth(config: VestaConfig) -> tuple[ProviderKind, bool]:
    """The usable provider and whether its credential is valid: none when no provider is chosen (fresh
    / signed out); openrouter when chosen (key is type-guaranteed); claude when chosen, authed only if
    the OAuth blob loaded from disk is valid (an expired/absent blob is claude-but-unauthenticated)."""
    provider = config.provider
    if provider is None:
        return "none", False
    if isinstance(provider, OpenRouterConfig):
        return "openrouter", bool(provider.key.get_secret_value())
    # A config built outside load_config (validation paths never hydrate) carries oauth=None;
    # read the blob from disk here so status derivation stays an honest reading of what's on disk.
    oauth = provider.oauth if provider.oauth is not None else read_claude_oauth()
    return "claude", oauth is not None and _check_claude_oauth(oauth)


def _check_claude_oauth(oauth: ClaudeOAuth) -> bool:
    """A refresh token lets the SDK mint a fresh access token on demand, so an expired expiresAt isn't
    a problem — the SDK refreshes transparently."""
    if isinstance(oauth.refresh_token, str) and oauth.refresh_token:
        return True
    if isinstance(oauth.expires_at, int):
        return oauth.expires_at > int(time.time() * 1000)
    return False


# --- Plan usage (provider-agnostic) ---
#
# Each provider reports usage in its own upstream shape — Claude as time-windowed rate-limit buckets
# (/api/oauth/usage), OpenRouter as a spend balance (/api/v1/key). We normalize both to `meters`
# (quota used as a %, optionally with a reset time) plus `credits` (a spend balance), so the API and
# UI never special-case a provider. Dispatch mirrors derive_status.


@dc.dataclass
class UsageMeter:
    label: str
    used_pct: float | None
    resets_at: str | None


@dc.dataclass
class UsageCredits:
    used: float | None
    limit: float | None


@dc.dataclass
class Usage:
    meters: list[UsageMeter]
    credits: UsageCredits | None


class UsageError(Exception):
    """An upstream usage fetch failed (network, timeout, or non-200). The handler maps it to an
    error response; the UI shows 'failed to load' rather than stale or fabricated numbers."""


# Claude's /api/oauth/usage buckets we surface, in display order, mapped to provider-agnostic labels.
_CLAUDE_USAGE_METERS = (
    ("five_hour", "current session"),
    ("seven_day", "current week"),
    ("seven_day_sonnet", "current week (sonnet)"),
    ("seven_day_opus", "current week (opus)"),
)


def _as_float(value: pyd.JsonValue) -> float | None:
    return value if isinstance(value, int | float) and not isinstance(value, bool) else None


def _as_str(value: pyd.JsonValue) -> str | None:
    return value if isinstance(value, str) else None


def _read_oauth_token() -> str | None:
    try:
        data = json.loads(CREDENTIALS_PATH.read_text())
        return data["claudeAiOauth"]["accessToken"]
    except (OSError, KeyError, json.JSONDecodeError):
        return None


async def get_usage(config: VestaConfig) -> Usage:
    """Provider-agnostic plan usage for the agent's active provider. Returns empty usage when no
    provider is configured; raises UsageError when an upstream fetch fails."""
    kind, _ = _derive_kind_and_auth(config)
    if kind == "claude":
        return await _claude_usage()
    if kind == "openrouter":
        return await _openrouter_usage(config)
    return Usage(meters=[], credits=None)


async def _claude_usage() -> Usage:
    token = _read_oauth_token()
    if token is None:
        raise UsageError("no oauth credentials")
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": OAUTH_BETA_HEADER,
        "Content-Type": "application/json",
        "User-Agent": _USAGE_USER_AGENT,
    }
    data = await _fetch_usage_json(f"{ANTHROPIC_API_URL}/api/oauth/usage", headers=headers)
    meters = []
    for key, label in _CLAUDE_USAGE_METERS:
        bucket_raw = data[key] if key in data else None
        bucket = bucket_raw if isinstance(bucket_raw, dict) else None
        if bucket is not None and "utilization" in bucket:
            meters.append(
                UsageMeter(
                    label=label,
                    used_pct=_as_float(bucket["utilization"]),
                    resets_at=_as_str(bucket["resets_at"]) if "resets_at" in bucket else None,
                )
            )
    usage_credits = None
    extra_raw = data["extra_usage"] if "extra_usage" in data else None
    extra = extra_raw if isinstance(extra_raw, dict) else None
    if extra is not None and "is_enabled" in extra and extra["is_enabled"]:
        # Anthropic reports extra-usage in cents; normalize to dollars to match OpenRouter's units.
        used_credits = _as_float(extra["used_credits"]) if "used_credits" in extra else None
        monthly_limit = _as_float(extra["monthly_limit"]) if "monthly_limit" in extra else None
        used = used_credits / 100 if used_credits is not None else None
        limit = monthly_limit / 100 if monthly_limit is not None else None
        usage_credits = UsageCredits(used=used, limit=limit)
    return Usage(meters=meters, credits=usage_credits)


async def _openrouter_usage(config: VestaConfig) -> Usage:
    if not isinstance(config.provider, OpenRouterConfig):
        raise UsageError("no openrouter key")
    headers = {"Authorization": f"Bearer {config.provider.key.get_secret_value()}"}
    data = await _fetch_usage_json(OPENROUTER_KEY_URL, headers=headers)
    # OpenRouter wraps the payload in {"data": {...}}; usage and limit are already in dollars.
    payload_raw = data["data"] if "data" in data else None
    payload = payload_raw if isinstance(payload_raw, dict) else {}
    used = _as_float(payload["usage"]) if "usage" in payload else None
    limit = _as_float(payload["limit"]) if "limit" in payload else None
    return Usage(meters=[], credits=UsageCredits(used=used, limit=limit))


async def _fetch_usage_json(url: str, *, headers: dict[str, str]) -> dict[str, pyd.JsonValue]:
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=_USAGE_TIMEOUT_S)) as resp,
        ):
            if resp.status != 200:
                # Read as text first: an upstream error body may not be JSON, so resp.json() would
                # raise and mask the real status.
                body = await resp.text()
                raise UsageError(f"upstream returned {resp.status}: {body[:200]}")
            return await resp.json()
    except (TimeoutError, aiohttp.ClientError) as e:
        raise UsageError(str(e)) from e
