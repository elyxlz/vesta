"""Per-agent LLM-provider auth and subscription credentials."""

import dataclasses as dc
import enum
import json
import pathlib as pl
import time
import typing as tp

import aiohttp
import pydantic as pyd

from . import logger
from .config import (
    CREDENTIALS_PATH,
    ClaudeConfig,
    ClaudeOAuth,
    KeyProviderKind,
    KimiConfig,
    OpenAIConfig,
    OpenRouterConfig,
    ProviderKind,
    VestaConfig,
    ZaiConfig,
    atomic_write_text,
    codex_proxy_auth_path,
    config_store_path,
    config_write_lock,
    read_claude_oauth,
    update_config_store,
    validate_config_updates,
)

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


ProviderStatusKind = ProviderKind | tp.Literal["none"]

# What normally counts as a terminal provider error — the credential is rejected (401) or the
# account can't pay (402). Kimi overloads both statuses, so its Claude-harness path additionally
# uses the documented error text in is_terminal_provider_error below.
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


_KIMI_INVALID_CREDENTIAL_MARKERS = (
    "api key appears to be invalid or may have expired",
    "invalid authentication",
)


def is_terminal_provider_error(
    kind: "ProviderStatusKind | None",
    *,
    assistant_error: str | None,
    api_error_status: int | None,
    details: tp.Iterable[str] = (),
) -> bool:
    """Classify a streamed provider failure without treating Kimi entitlement errors as logout.

    Kimi documents 401 for both invalid credentials and valid subscriptions lacking K3, 1M, or
    HighSpeed access; it also uses 402 when membership verification is temporarily unavailable.
    Only its two explicit credential messages are therefore terminal. Other providers retain the
    SDK's 401/402 classification.
    """
    if kind == "kimi":
        is_401 = assistant_error == "authentication_failed" or api_error_status == 401
        if not is_401:
            return False
        text = "\n".join(details).lower()
        return any(marker in text for marker in _KIMI_INVALID_CREDENTIAL_MARKERS)
    return is_terminal_auth_error(assistant_error) or api_error_status in TERMINAL_PROVIDER_ERRORS


def is_unauthenticated(status: "ProviderStatus | None") -> bool:
    """The "dead token" predicate: gates handing prompts to the CLI (the processor's deferral
    and send_preempt) so a known-bad credential doesn't burn the CLI's retry budget."""
    return status is not None and status.state == ProviderAuthState.NOT_AUTHENTICATED


@dc.dataclass
class ProviderStatus:
    state: ProviderAuthState
    kind: ProviderStatusKind
    model: str | None

    def __post_init__(self) -> None:
        # The model is only meaningful for an authenticated provider; an agent whose credentials are
        # missing or invalidated (boot derive or a runtime 401/402 flip) isn't using any model, so it
        # reports none. Enforced here so every construction path — including dc.replace — converges.
        if self.state != ProviderAuthState.AUTHENTICATED:
            self.model = None


def derive_status(config: VestaConfig) -> ProviderStatus:
    """Re-derive provider status at boot, purely from disk: the config store (provider + key) and
    `.credentials.json`. On-disk state is the single source of truth — a runtime auth failure is an
    in-memory flip only (see observed_provider_failure), so boot is always an honest reading of what's
    actually provisioned. Model comes from the config store via VestaConfig."""
    kind, authed = _derive_kind_and_auth(config)
    state = ProviderAuthState.AUTHENTICATED if authed else ProviderAuthState.NOT_AUTHENTICATED
    model = config.provider.model if config.provider is not None else None
    return ProviderStatus(state=state, kind=kind, model=model)


def _validated_sign_in(
    kind: str,
    *,
    model: str | None,
    max_context_tokens: int | None,
    key: str | None,
    config: VestaConfig,
) -> dict[str, pyd.JsonValue]:
    """Build and validate a complete provider before any credential or config write."""
    patch: dict[str, pyd.JsonValue] = {"kind": kind}
    if model is not None:
        patch["model"] = model
    if max_context_tokens is not None:
        patch["max_context_tokens"] = max_context_tokens
    if key is not None:
        patch["key"] = key
    updates = validate_config_updates(config, {"provider": patch})
    provider = updates.get("provider")
    if not isinstance(provider, dict):  # validate_config_updates guarantees this; keep the boundary explicit.
        raise TypeError("validated provider is not an object")
    return tp.cast("dict[str, pyd.JsonValue]", provider)


def _persist_sign_in(provider: dict[str, pyd.JsonValue]) -> str | None:
    update_config_store({"provider": provider})
    model = provider.get("model")
    return model if isinstance(model, str) else None


def _clear_inactive_credentials(kind: ProviderStatusKind) -> None:
    """Remove reusable OAuth tokens not owned by the provider being activated.

    The Claude harness can read the agent's home directory, so retaining an inactive provider's
    refresh token would unnecessarily expose it to the newly active session.
    """
    if kind != "claude":
        CREDENTIALS_PATH.unlink(missing_ok=True)
    if kind != "openai":
        codex_proxy_auth_path().unlink(missing_ok=True)


def _snapshot_files(paths: tp.Iterable[pl.Path]) -> dict[pl.Path, tuple[str | None, int | None]]:
    snapshots: dict[pl.Path, tuple[str | None, int | None]] = {}
    for path in paths:
        try:
            snapshots[path] = (path.read_text(), path.stat().st_mode & 0o777)
        except FileNotFoundError:
            snapshots[path] = (None, None)
    return snapshots


def _restore_files(snapshots: dict[pl.Path, tuple[str | None, int | None]]) -> None:
    for path, (content, mode) in snapshots.items():
        try:
            if content is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_text(path, content)
                if mode is not None:
                    path.chmod(mode)
        except OSError as exc:
            logger.error(f"Failed to roll back provider file {path}: {exc}")


def _apply_sign_in(
    provider: dict[str, pyd.JsonValue],
    *,
    credential_writes: dict[pl.Path, str] | None = None,
) -> str | None:
    """Commit already-validated config and credentials; caller holds the config transaction lock."""
    paths = {config_store_path(), CREDENTIALS_PATH, codex_proxy_auth_path(), CLAUDE_JSON_PATH}
    snapshots = _snapshot_files(paths)
    kind = tp.cast("ProviderKind", provider["kind"])
    try:
        for path, content in (credential_writes or {}).items():
            atomic_write_text(path, content)
        reported = _persist_sign_in(provider)
        _clear_inactive_credentials(kind)
    except Exception:
        _restore_files(snapshots)
        raise
    return reported


def _commit_sign_in(
    kind: ProviderKind,
    *,
    model: str | None,
    max_context_tokens: int | None,
    key: str | None,
    config: VestaConfig,
    credential_writes: dict[pl.Path, str] | None = None,
) -> str | None:
    """Validate from the latest store state and apply the whole sign-in as one serialized unit."""
    with config_write_lock():
        provider = _validated_sign_in(
            kind,
            model=model,
            max_context_tokens=max_context_tokens,
            key=key,
            config=config,
        )
        return _apply_sign_in(provider, credential_writes=credential_writes)


def enforce_active_credentials(config: VestaConfig) -> None:
    """Delete inactive tokens at boot only when the raw store confirms the loaded provider.

    A corrupt or newly incompatible store makes load_config recover with defaults. Never use that
    fallback to delete credentials belonging to the provider the raw store intended.
    """
    kind = config.provider.kind if config.provider is not None else "none"
    store_path = config_store_path()
    if store_path.exists():
        try:
            raw = json.loads(store_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"Skipping inactive OAuth cleanup because config store is unreadable: {exc}")
            return
        raw_provider = raw.get("provider") if isinstance(raw, dict) else None
        raw_kind = raw_provider.get("kind") if isinstance(raw_provider, dict) else "none"
        if raw_kind != kind:
            logger.warning(f"Skipping inactive OAuth cleanup because raw provider {raw_kind!r} differs from loaded {kind!r}")
            return
    _clear_inactive_credentials(kind)


def set_claude(credentials_json: str, model: str | None, max_context_tokens: int | None, *, config: VestaConfig) -> ProviderStatus:
    """Write the Claude OAuth credentials to the SDK path and merge a claude provider patch into the
    store (model/context unspecified on re-auth are preserved). The OAuth blob lives in the credentials
    file, never the store."""
    # Validate every input before touching either credential or config file so a bad provider
    # choice cannot leave credentials half-applied.
    credentials = json.loads(credentials_json)
    if not isinstance(credentials, dict) or not isinstance(credentials.get("claudeAiOauth"), dict):
        raise ValueError("Claude credentials must contain claudeAiOauth")
    oauth = ClaudeOAuth.model_validate(credentials["claudeAiOauth"])
    if not _check_claude_oauth(oauth):
        raise ValueError("Claude credentials contain no usable access or refresh token")
    reported = _commit_sign_in(
        "claude",
        model=model,
        max_context_tokens=max_context_tokens,
        key=None,
        config=config,
        credential_writes={CREDENTIALS_PATH: credentials_json, CLAUDE_JSON_PATH: '{"hasCompletedOnboarding":true}'},
    )
    logger.startup("Provider set to claude")
    return ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model=reported)


def set_key_provider(
    kind: KeyProviderKind,
    key: str,
    model: str,
    max_context_tokens: int | None,
    *,
    config: VestaConfig,
) -> ProviderStatus:
    """Validate and store any key-backed provider through the shared credential transaction."""
    reported = _commit_sign_in(
        kind,
        model=model,
        max_context_tokens=max_context_tokens,
        key=key,
        config=config,
    )
    logger.startup(f"Provider set to {kind} model={model}")
    return ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind=kind, model=reported)


_NonBlankCredential = tp.Annotated[str, pyd.StringConstraints(strip_whitespace=True, min_length=1)]


class _OpenAICredentials(pyd.BaseModel):
    access: _NonBlankCredential
    refresh: _NonBlankCredential
    expires: int = pyd.Field(gt=0)
    account_id: str | None = pyd.Field(default=None, alias="accountId")

    model_config = pyd.ConfigDict(populate_by_name=True)


def set_openai(credentials_json: str, model: str, max_context_tokens: int | None, *, config: VestaConfig) -> ProviderStatus:
    """Store refreshable ChatGPT OAuth for the local Claude-harness bridge."""
    credentials = _OpenAICredentials.model_validate_json(credentials_json)
    path = codex_proxy_auth_path()
    reported = _commit_sign_in(
        "openai",
        model=model,
        max_context_tokens=max_context_tokens,
        key=None,
        config=config,
        credential_writes={path: credentials.model_dump_json(by_alias=True, exclude_none=True)},
    )
    logger.startup(f"Provider set to openai model={model}")
    return ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="openai", model=reported)


def clear_provider() -> ProviderStatus:
    """Sign out: remove the Claude OAuth blob and clear the stored provider to None (no provider
    chosen), leaving the agent unprovisioned. General config (personality, timezone, ...) survives.
    Vestad restarts the agent."""
    with config_write_lock():
        paths = {config_store_path(), CREDENTIALS_PATH, codex_proxy_auth_path()}
        snapshots = _snapshot_files(paths)
        try:
            CREDENTIALS_PATH.unlink(missing_ok=True)
            codex_proxy_auth_path().unlink(missing_ok=True)
            update_config_store({"provider": None})
        except Exception:
            _restore_files(snapshots)
            raise
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


def _derive_kind_and_auth(config: VestaConfig) -> tuple[ProviderStatusKind, bool]:
    """The usable provider and whether its credential is valid: none when no provider is chosen (fresh
    / signed out); openrouter when chosen (key is type-guaranteed); claude when chosen, authed only if
    the OAuth blob loaded from disk is valid (an expired/absent blob is claude-but-unauthenticated)."""
    provider = config.provider
    if provider is None:
        return "none", False
    if isinstance(provider, (OpenRouterConfig, ZaiConfig, KimiConfig)):
        return provider.kind, bool(provider.key.get_secret_value())
    if isinstance(provider, OpenAIConfig):
        try:
            _OpenAICredentials.model_validate_json(codex_proxy_auth_path().read_text())
        except (OSError, pyd.ValidationError):
            return "openai", False
        return "openai", True  # the validated refresh token can replace an expired access token
    # A config built outside load_config (validation paths never hydrate) carries oauth=None;
    # read the blob from disk here so status derivation stays an honest reading of what's on disk.
    if isinstance(provider, ClaudeConfig):
        oauth = provider.oauth if provider.oauth is not None else read_claude_oauth()
        return "claude", oauth is not None and _check_claude_oauth(oauth)
    return "none", False


def _check_claude_oauth(oauth: ClaudeOAuth) -> bool:
    """A refresh token lets the SDK mint a fresh access token on demand, so an expired expiresAt isn't
    a problem — the SDK refreshes transparently."""
    if isinstance(oauth.refresh_token, str) and oauth.refresh_token.strip():
        return True
    if isinstance(oauth.access_token, str) and oauth.access_token.strip() and isinstance(oauth.expires_at, int):
        return oauth.expires_at > int(time.time() * 1000)
    return False


# --- Plan usage (provider-agnostic) ---
#
# Providers with upstream usage APIs report different shapes — Claude as time-windowed rate-limit
# buckets and OpenRouter as a spend balance. We normalize those to `meters` plus `credits`; providers
# without a usage endpoint return an empty result.


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
