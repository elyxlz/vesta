"""Per-agent LLM-provider authentication state.

This is the agent's relationship with its upstream LLM provider (Claude OAuth or
OpenRouter API key), NOT the agent's own HTTP API auth (that's the X-Agent-Token
middleware in `api.py`), and NOT the agent's editable preferences (model, context
window, personality), which live in the writable config store (`config.py`, PUT /config).

`vesta-provider.env` holds only the provider CHOICE and credentials: AGENT_PROVIDER,
the OpenRouter key, and the OpenRouter small-fast model. The selected model and context
window live in the config store; the Claude OAuth blob lives in `.credentials.json`. Each
mutation persists the auth state to PersistedState so a runtime failure isn't silently
forgotten across a container restart (e.g. dreamer).
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
PROVIDER_ENV_PATH = pl.Path.home() / ".claude" / "vesta-provider.env"

# Cheap haiku-class model the SDK reaches for on background work (compaction probes,
# summarization, intent classification). Hardcoded so picking an expensive primary
# model doesn't silently 5–10× background spend. Editable in the provider file post-create.
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
    """Re-derive provider status at boot. The provider CHOICE comes from disk (the provider
    file or bare credentials); the model and context window come from the config store via
    VestaConfig, so the auth subsystem no longer carries them."""
    kind = _derive_kind()
    # If we recorded a 401 in a prior boot, honor it — otherwise derive from disk.
    if persisted.provider_auth_state == ProviderAuthState.NOT_AUTHENTICATED.value:
        state = ProviderAuthState.NOT_AUTHENTICATED
    else:
        state = _derive_state_from_disk(kind)
    model = config.agent_model if kind != "none" else None
    return ProviderStatus(state=state, kind=kind, model=model, max_context_tokens=config.max_context_tokens)


def set_claude(credentials_json: str, *, config: VestaConfig, persisted: PersistedState) -> ProviderStatus:
    """Write Claude OAuth credentials + the Claude provider file and return the new
    (authenticated) status. The provider file records AGENT_PROVIDER=claude and clears the
    OpenRouter exports, so switching OpenRouter->Claude leaves no stale token/base-url behind.
    The model and context window are not touched here; they live in the config store and the
    shipped default (a Claude model) applies until a PUT /config changes them."""
    # Validate JSON shape before touching disk so we don't half-apply on bad input.
    json.loads(credentials_json)
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(credentials_json)
    CLAUDE_JSON_PATH.write_text('{"hasCompletedOnboarding":true}')
    _write_provider_file(_claude_provider_file())
    status = ProviderStatus(
        state=ProviderAuthState.AUTHENTICATED, kind="claude", model=config.agent_model, max_context_tokens=config.max_context_tokens
    )
    _persist(status, config=config, persisted=persisted)
    logger.startup("Provider set to claude")
    return status


def set_openrouter(key: str, model: str, *, config: VestaConfig, persisted: PersistedState) -> ProviderStatus:
    """Write the OpenRouter provider env file (key only) and record the selected model in the
    config store. OpenRouter is non-functional without a valid model, so switching to it sets
    the model in one call rather than risking a boot on a Claude default. The agent must be
    restarted by vestad for the provider env vars to take effect. Context window is unchanged
    here (a PUT /config sets it)."""
    update_config_store({"agent_model": model})
    _write_provider_file(_openrouter_provider_file(key))
    status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="openrouter", model=model, max_context_tokens=config.max_context_tokens)
    _persist(status, config=config, persisted=persisted)
    logger.startup(f"Provider set to openrouter model={model}")
    return status


def observed_provider_failure(status: ProviderStatus | None, *, config: VestaConfig, persisted: PersistedState) -> ProviderStatus | None:
    """Called by the SDK response-stream handler on a terminal upstream auth/billing
    error (401 invalid auth, 402 insufficient credits). Returns the status flipped to
    NOT_AUTHENTICATED (persisted so it survives a restart), or the input unchanged when
    there's nothing to flip. A flipped provider needs re-provisioning to recover (a 402
    won't clear on its own until the key has credits and the agent is re-provisioned)."""
    if status is None or status.state == ProviderAuthState.NOT_AUTHENTICATED:
        return status
    new_status = dc.replace(status, state=ProviderAuthState.NOT_AUTHENTICATED)
    _persist(new_status, config=config, persisted=persisted)
    logger.error(f"Provider {new_status.kind} flipped to not_authenticated (upstream auth/billing error)")
    return new_status


def _persist(status: ProviderStatus, *, config: VestaConfig, persisted: PersistedState) -> None:
    persisted.provider_auth_state = status.state.value
    save_state(persisted, config)


def _derive_kind() -> ProviderKind:
    """The provider CHOICE: the provider file's AGENT_PROVIDER wins; otherwise bare Claude
    credentials count as claude; otherwise none. The model is no longer read here (it lives in
    the config store), so a legacy/empty provider file still resolves the right kind."""
    if PROVIDER_ENV_PATH.exists():
        provider = _parse_first_export(PROVIDER_ENV_PATH.read_text(), "AGENT_PROVIDER")
        if provider in ("openrouter", "claude"):
            return tp.cast(ProviderKind, provider)
    if CREDENTIALS_PATH.exists():
        return "claude"
    return "none"


def _derive_state_from_disk(kind: ProviderKind) -> ProviderAuthState:
    if kind == "openrouter":
        content = PROVIDER_ENV_PATH.read_text()
        ok = _provider_declares_openrouter(content) and _openrouter_token_present(content)
    elif kind == "claude":
        ok = CREDENTIALS_PATH.exists() and _check_claude_auth(CREDENTIALS_PATH.read_text())
    else:
        ok = False
    return ProviderAuthState.AUTHENTICATED if ok else ProviderAuthState.NOT_AUTHENTICATED


# --- File-format helpers (mirror of vestad/src/providers/openrouter.rs) ---


def _shell_single_quote(value: str) -> str:
    """Single-quote a value for safe shell sourcing; escapes embedded quotes."""
    escaped = value.replace("'", "'\\''")
    return f"'{escaped}'"


def _write_provider_file(content: str) -> None:
    PROVIDER_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROVIDER_ENV_PATH.write_text(content)


def _claude_provider_file() -> str:
    """The sourced shell file for Claude mode. Records only the provider choice and explicitly
    clears the OpenRouter exports so an OpenRouter->Claude switch leaves no stale token behind
    (Claude auth itself lives in .credentials.json; the model lives in the config store)."""
    return "export AGENT_PROVIDER=claude\nexport ANTHROPIC_AUTH_TOKEN=\nexport ANTHROPIC_API_KEY=\nexport ANTHROPIC_SMALL_FAST_MODEL=\n"


def _openrouter_provider_file(key: str) -> str:
    """The sourced shell file that puts an agent into OpenRouter mode: the provider choice, the
    key, and the small-fast background model. The selected model lives in the config store."""
    return (
        "export AGENT_PROVIDER=openrouter\n"
        f"export ANTHROPIC_AUTH_TOKEN={_shell_single_quote(key)}\n"
        "export ANTHROPIC_API_KEY=\n"
        f"export ANTHROPIC_SMALL_FAST_MODEL={_shell_single_quote(OPENROUTER_SMALL_FAST_MODEL)}\n"
    )


def _parse_shell_export(line: str, key: str) -> str | None:
    """Parse a `[export ]KEY=value` shell line, returning the unquoted value if
    `key` matches. Skips blanks and `#`-comments. Strips one layer of single quotes."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[len("export ") :]
    if "=" not in line:
        return None
    k, _, v = line.partition("=")
    if k.strip() != key:
        return None
    v = v.strip()
    if len(v) >= 2 and v.startswith("'") and v.endswith("'"):
        v = v[1:-1]
    return v


def _parse_first_export(content: str, key: str) -> str | None:
    for line in content.splitlines():
        parsed = _parse_shell_export(line, key)
        if parsed is not None:
            return parsed
    return None


def _provider_declares_openrouter(content: str) -> bool:
    return any(_parse_shell_export(line, "AGENT_PROVIDER") == "openrouter" for line in content.splitlines())


def _openrouter_token_present(content: str) -> bool:
    for line in content.splitlines():
        v = _parse_shell_export(line, "ANTHROPIC_AUTH_TOKEN")
        if v is not None and v:
            return True
    return False


def _check_claude_auth(content: str) -> bool:
    """A refresh token lets the SDK mint a fresh access token on demand, so an
    expired expiresAt isn't a problem — the SDK refreshes transparently."""
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
