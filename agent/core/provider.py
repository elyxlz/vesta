"""Per-agent LLM-provider authentication state.

This is the agent's relationship with its upstream LLM provider (Claude OAuth or
OpenRouter API key), NOT the agent's own HTTP API auth (that's the X-Agent-Token
middleware in `api.py`).

`ProviderStatus` is the in-memory state, derived at boot from PersistedState +
disk files via `derive_status`. It is replaced at runtime by:
- explicit writes via POST /provider (`set_claude` / `set_openrouter`)
- runtime 401 observations from the SDK stream (`observed_401`)

Each mutation persists to PersistedState so a runtime 401 isn't silently
forgotten across a container restart (e.g., dreamer-restart).
"""

import dataclasses as dc
import enum
import json
import pathlib as pl
import time
import typing as tp

from . import logger
from .config import VestaConfig
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


def derive_status(config: VestaConfig, persisted: PersistedState) -> ProviderStatus:
    """Re-derive provider status at boot from disk files + last persisted state."""
    kind, model = _derive_kind_and_model(config)
    # If we recorded a 401 in a prior boot, honor it — otherwise derive from disk.
    if persisted.provider_auth_state == ProviderAuthState.NOT_AUTHENTICATED.value:
        state = ProviderAuthState.NOT_AUTHENTICATED
    else:
        state = _derive_state_from_disk(kind)
    return ProviderStatus(state=state, kind=kind, model=model)


def set_claude(credentials_json: str, *, config: VestaConfig, persisted: PersistedState) -> ProviderStatus:
    """Write Claude OAuth credentials and return the new (authenticated) status.
    Clears any prior OpenRouter provider file so its env-var exports don't
    override the Claude creds at next boot."""
    # Validate JSON shape before touching disk so we don't half-apply on bad input.
    json.loads(credentials_json)
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(credentials_json)
    CLAUDE_JSON_PATH.write_text('{"hasCompletedOnboarding":true}')
    if PROVIDER_ENV_PATH.exists():
        PROVIDER_ENV_PATH.write_text("")
    status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model=config.agent_model)
    _persist(status, config=config, persisted=persisted)
    logger.startup("Provider set to claude (authenticated)")
    return status


def set_openrouter(key: str, model: str, *, config: VestaConfig, persisted: PersistedState) -> ProviderStatus:
    """Write the OpenRouter provider env file and return the new (authenticated)
    status. The agent must be restarted by vestad for the env vars to take effect."""
    PROVIDER_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROVIDER_ENV_PATH.write_text(_openrouter_provider_file(key, model))
    status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="openrouter", model=model)
    _persist(status, config=config, persisted=persisted)
    logger.startup(f"Provider set to openrouter model={model}")
    return status


def set_openrouter_model(model: str, *, config: VestaConfig, persisted: PersistedState) -> ProviderStatus:
    """Change only the model for an OpenRouter agent, preserving the stored key.
    Lets the app switch models without the user re-entering the API key. Raises
    if the agent isn't on OpenRouter or has no key on file to preserve."""
    if not PROVIDER_ENV_PATH.exists():
        raise ValueError("no OpenRouter provider configured")
    content = PROVIDER_ENV_PATH.read_text()
    if not _provider_declares_openrouter(content):
        raise ValueError("agent is not running on OpenRouter")
    key = _parse_first_export(content, "ANTHROPIC_AUTH_TOKEN")
    if not key:
        raise ValueError("no OpenRouter key on file to preserve")
    return set_openrouter(key, model, config=config, persisted=persisted)


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


def _derive_kind_and_model(config: VestaConfig) -> tuple[ProviderKind, str | None]:
    """Provider file's env exports win over Claude credentials at boot."""
    if PROVIDER_ENV_PATH.exists():
        content = PROVIDER_ENV_PATH.read_text()
        if _provider_declares_openrouter(content):
            model = _parse_first_export(content, "AGENT_MODEL") or config.agent_model
            return "openrouter", model
    if CREDENTIALS_PATH.exists():
        return "claude", config.agent_model
    return "none", None


def _derive_state_from_disk(kind: ProviderKind) -> ProviderAuthState:
    if kind == "openrouter":
        content = PROVIDER_ENV_PATH.read_text()
        ok = _provider_declares_openrouter(content) and _openrouter_token_present(content)
    elif kind == "claude":
        ok = _check_claude_auth(CREDENTIALS_PATH.read_text())
    else:
        ok = False
    return ProviderAuthState.AUTHENTICATED if ok else ProviderAuthState.NOT_AUTHENTICATED


# --- File-format helpers (mirror of vestad/src/providers/openrouter.rs) ---


def _shell_single_quote(value: str) -> str:
    """Single-quote a value for safe shell sourcing; escapes embedded quotes."""
    escaped = value.replace("'", "'\\''")
    return f"'{escaped}'"


def _openrouter_provider_file(key: str, model: str) -> str:
    """The sourced shell file that puts an agent into OpenRouter mode."""
    return (
        "export AGENT_PROVIDER=openrouter\n"
        f"export AGENT_MODEL={_shell_single_quote(model)}\n"
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
