"""Per-agent LLM-provider auth (Claude OAuth or OpenRouter key). The provider choice and OpenRouter
key live in the config store; the Claude OAuth blob lives in `.credentials.json` (the `claude` CLI
reads it). Each mutation persists the auth state to PersistedState so it survives a restart."""

import dataclasses as dc
import enum
import json
import pathlib as pl
import time
import typing as tp

import aiohttp

from . import logger
from .config import PROVIDER_PREF_FIELDS, VestaConfig, update_config_store
from .state_store import PersistedState, save_state

CREDENTIALS_PATH = pl.Path.home() / ".claude" / ".credentials.json"
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


@dc.dataclass
class ProviderStatus:
    state: ProviderAuthState
    kind: ProviderKind
    model: str | None
    max_context_tokens: int | None = None

    def __post_init__(self) -> None:
        # The model is only meaningful for an authenticated provider; an agent whose credentials are
        # missing or invalidated (boot derive or a runtime 401/402 flip) isn't using any model, so it
        # reports none. Enforced here so every construction path — including dc.replace — converges.
        if self.state != ProviderAuthState.AUTHENTICATED:
            self.model = None


def derive_status(config: VestaConfig, persisted: PersistedState) -> ProviderStatus:
    """Re-derive provider status at boot from the config store (provider + key) and
    `.credentials.json`. The model and context window come from the config store via VestaConfig."""
    kind, authed = _derive_kind_and_auth(config)
    # A 401 recorded in a prior boot overrides the on-disk reading.
    if persisted.provider_auth_state == ProviderAuthState.NOT_AUTHENTICATED.value:
        authed = False
    state = ProviderAuthState.AUTHENTICATED if authed else ProviderAuthState.NOT_AUTHENTICATED
    return ProviderStatus(state=state, kind=kind, model=config.agent_model, max_context_tokens=config.max_context_tokens)


def set_claude(credentials_json: str, *, config: VestaConfig, persisted: PersistedState) -> ProviderStatus:
    """Write the Claude OAuth credentials, set the provider to claude in the config store, and clear
    any OpenRouter key, returning the authenticated status."""
    # Validate JSON shape before touching disk so we don't half-apply on bad input.
    json.loads(credentials_json)
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(credentials_json)
    CLAUDE_JSON_PATH.write_text('{"hasCompletedOnboarding":true}')
    update_config_store({"agent_provider": "claude", "openrouter_key": None})
    status = ProviderStatus(
        state=ProviderAuthState.AUTHENTICATED, kind="claude", model=config.agent_model, max_context_tokens=config.max_context_tokens
    )
    _persist(status, config=config, persisted=persisted)
    logger.startup("Provider set to claude")
    return status


def set_openrouter(key: str, model: str, *, config: VestaConfig, persisted: PersistedState) -> ProviderStatus:
    """Record the OpenRouter provider, key, and model in the config store (OpenRouter needs a valid
    model). Vestad restarts the agent to apply it."""
    update_config_store({"agent_provider": "openrouter", "openrouter_key": key, "agent_model": model})
    status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="openrouter", model=model, max_context_tokens=config.max_context_tokens)
    _persist(status, config=config, persisted=persisted)
    logger.startup(f"Provider set to openrouter model={model}")
    return status


def clear_provider(*, config: VestaConfig, persisted: PersistedState) -> ProviderStatus:
    """Sign out: clear everything provider-owned — the Claude OAuth blob, the OpenRouter key, and the
    provider preferences (model, context, thinking) — leaving the agent not_authenticated. Only
    general config (e.g. personality) survives; the provider choice is kept as the last-used hint.
    Vestad restarts the agent."""
    CREDENTIALS_PATH.unlink(missing_ok=True)
    update_config_store({"openrouter_key": None, **{field: None for field in PROVIDER_PREF_FIELDS}})
    status = ProviderStatus(state=ProviderAuthState.NOT_AUTHENTICATED, kind=config.agent_provider, model=None, max_context_tokens=None)
    _persist(status, config=config, persisted=persisted)
    logger.startup("Provider cleared (signed out)")
    return status


def observed_provider_failure(status: ProviderStatus | None, *, config: VestaConfig, persisted: PersistedState) -> ProviderStatus | None:
    """Called by the SDK response-stream handler on a terminal upstream auth/billing error (401
    invalid auth, 402 insufficient credits). Returns the status flipped to NOT_AUTHENTICATED
    (persisted so it survives a restart), or the input unchanged when there's nothing to flip."""
    if status is None or status.state == ProviderAuthState.NOT_AUTHENTICATED:
        return status
    new_status = dc.replace(status, state=ProviderAuthState.NOT_AUTHENTICATED)
    _persist(new_status, config=config, persisted=persisted)
    logger.error(f"Provider {new_status.kind} flipped to not_authenticated (upstream auth/billing error)")
    return new_status


def _persist(status: ProviderStatus, *, config: VestaConfig, persisted: PersistedState) -> None:
    persisted.provider_auth_state = status.state.value
    save_state(persisted, config)


def _derive_kind_and_auth(config: VestaConfig) -> tuple[ProviderKind, bool]:
    """The usable provider and whether its credential is valid: openrouter when chosen with a key,
    claude when the OAuth blob is on disk, else none (a fresh, unprovisioned agent)."""
    if config.agent_provider == "openrouter" and config.openrouter_key is not None:
        return "openrouter", bool(config.openrouter_key.get_secret_value())
    if CREDENTIALS_PATH.exists():
        return "claude", _check_claude_auth(CREDENTIALS_PATH.read_text())
    return "none", False


def _check_claude_auth(content: str) -> bool:
    """A refresh token lets the SDK mint a fresh access token on demand, so an expired expiresAt
    isn't a problem — the SDK refreshes transparently."""
    try:
        creds = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return False
    oauth = creds["claudeAiOauth"] if isinstance(creds, dict) and "claudeAiOauth" in creds else None
    if not isinstance(oauth, dict):
        return False
    refresh = oauth["refreshToken"] if "refreshToken" in oauth else None
    if isinstance(refresh, str) and refresh:
        return True
    expires_at = oauth["expiresAt"] if "expiresAt" in oauth else None
    if isinstance(expires_at, int):
        return expires_at > int(time.time() * 1000)
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
        bucket = data[key] if key in data and isinstance(data[key], dict) else None
        if bucket is not None and "utilization" in bucket:
            meters.append(
                UsageMeter(label=label, used_pct=bucket["utilization"], resets_at=bucket["resets_at"] if "resets_at" in bucket else None)
            )
    credits = None
    extra = data["extra_usage"] if "extra_usage" in data and isinstance(data["extra_usage"], dict) else None
    if extra is not None and "is_enabled" in extra and extra["is_enabled"]:
        # Anthropic reports extra-usage in cents; normalize to dollars to match OpenRouter's units.
        used = extra["used_credits"] / 100 if "used_credits" in extra and extra["used_credits"] is not None else None
        limit = extra["monthly_limit"] / 100 if "monthly_limit" in extra and extra["monthly_limit"] is not None else None
        credits = UsageCredits(used=used, limit=limit)
    return Usage(meters=meters, credits=credits)


async def _openrouter_usage(config: VestaConfig) -> Usage:
    if config.openrouter_key is None:
        raise UsageError("no openrouter key")
    headers = {"Authorization": f"Bearer {config.openrouter_key.get_secret_value()}"}
    data = await _fetch_usage_json(OPENROUTER_KEY_URL, headers=headers)
    # OpenRouter wraps the payload in {"data": {...}}; usage and limit are already in dollars.
    payload = data["data"] if "data" in data and isinstance(data["data"], dict) else {}
    used = payload["usage"] if "usage" in payload else None
    limit = payload["limit"] if "limit" in payload else None
    return Usage(meters=[], credits=UsageCredits(used=used, limit=limit))


async def _fetch_usage_json(url: str, *, headers: dict[str, str]) -> dict[str, tp.Any]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=_USAGE_TIMEOUT_S)) as resp:
                if resp.status != 200:
                    # Read as text first: an upstream error body may not be JSON, so resp.json() would
                    # raise and mask the real status.
                    body = await resp.text()
                    raise UsageError(f"upstream returned {resp.status}: {body[:200]}")
                return await resp.json()
    except (TimeoutError, aiohttp.ClientError) as e:
        raise UsageError(str(e)) from e
