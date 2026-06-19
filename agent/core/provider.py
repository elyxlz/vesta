"""Per-agent LLM-provider authentication: the agent's relationship with its upstream provider
(Claude OAuth or OpenRouter API key).

The provider choice and the OpenRouter key live in the config store (`config.py`); the Claude OAuth
blob lives in `.credentials.json`, which the `claude` CLI reads directly. Each mutation persists the
auth state to PersistedState so it survives a restart. The agent's own HTTP API auth is the
X-Agent-Token middleware in `api.py`.
"""

import dataclasses as dc
import enum
import json
import pathlib as pl
import time
import typing as tp

from . import logger
from .config import VestaConfig, update_config_store
from .state_store import PersistedState, save_state

CREDENTIALS_PATH = pl.Path.home() / ".claude" / ".credentials.json"
CLAUDE_JSON_PATH = pl.Path.home() / ".claude.json"

# Cheap haiku-class model the SDK reaches for on background work (compaction probes,
# summarization, intent classification). Hardcoded so picking an expensive primary model
# doesn't silently 5–10× background spend.
OPENROUTER_SMALL_FAST_MODEL = "anthropic/claude-haiku-4.5"


class ProviderAuthState(enum.StrEnum):
    AUTHENTICATED = "authenticated"
    NOT_AUTHENTICATED = "not_authenticated"


ProviderKind = tp.Literal["claude", "openrouter", "none"]


@dc.dataclass
class ProviderStatus:
    state: ProviderAuthState
    kind: ProviderKind
    model: str | None
    max_context_tokens: int | None = None


def derive_status(config: VestaConfig, persisted: PersistedState) -> ProviderStatus:
    """Re-derive provider status at boot from the config store (provider + key) and
    `.credentials.json`. The model and context window come from the config store via VestaConfig."""
    kind = _derive_kind(config)
    # If we recorded a 401 in a prior boot, honor it — otherwise derive from disk.
    if persisted.provider_auth_state == ProviderAuthState.NOT_AUTHENTICATED.value:
        state = ProviderAuthState.NOT_AUTHENTICATED
    else:
        state = _derive_state_from_disk(kind, config)
    model = config.agent_model if kind != "none" else None
    return ProviderStatus(state=state, kind=kind, model=model, max_context_tokens=config.max_context_tokens)


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


def _derive_kind(config: VestaConfig) -> ProviderKind:
    """The usable provider: openrouter when chosen and a key is present, claude when the OAuth blob
    is on disk, else none (e.g. a fresh agent that hasn't been provisioned)."""
    if config.agent_provider == "openrouter" and config.openrouter_key is not None:
        return "openrouter"
    if CREDENTIALS_PATH.exists():
        return "claude"
    return "none"


def _derive_state_from_disk(kind: ProviderKind, config: VestaConfig) -> ProviderAuthState:
    if kind == "openrouter":
        ok = config.openrouter_key is not None and bool(config.openrouter_key.get_secret_value())
    elif kind == "claude":
        ok = CREDENTIALS_PATH.exists() and _check_claude_auth(CREDENTIALS_PATH.read_text())
    else:
        ok = False
    return ProviderAuthState.AUTHENTICATED if ok else ProviderAuthState.NOT_AUTHENTICATED


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
