import copy
import json
import os
import pathlib as pl
import time
import typing as tp

import pydantic as pyd
import pydantic_settings as pyd_settings
from core import logger
from claude_agent_sdk.types import ThinkingConfigAdaptive, ThinkingConfigDisabled, ThinkingConfigEnabled


_DEFAULT_AGENT_DIR = pl.Path.home() / "agent"
_THINKING_ENABLED_BUDGET_TOKENS = 10000

# The Claude OAuth blob lives at the SDK-owned path: the `claude` CLI reads AND refreshes it in place,
# so it is never persisted into the config store. Owned here (config.py is the lower-level module);
# provider.py re-exports it.
CREDENTIALS_PATH = pl.Path.home() / ".claude" / ".credentials.json"

# The hand-authored provider/setup catalog + new-agent defaults. It is the single source of that
# reference data: the Python model reads it for its field defaults (below), vestad embeds + serves it at
# GET /manifest (merging in the personality presets), and web/cli read it. No generation step.
MANIFEST_PATH = pl.Path(__file__).parent / "manifest.json"

# A tiny floor so a corrupt/missing manifest can never crash-loop the boot path (it never happens in
# practice; the file ships with the agent).
_MANIFEST_FALLBACK: dict[str, pyd.JsonValue] = {
    "default_provider": "claude",
    "default_personality": "dry",
    "providers": {"claude": {"default_model": "opus"}},
}


def read_manifest() -> dict[str, pyd.JsonValue]:
    """The shipped manifest as a dict (catalog + defaults). Never raises (it's read at import + boot)."""
    try:
        data = json.loads(MANIFEST_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return _MANIFEST_FALLBACK
    return data if isinstance(data, dict) else _MANIFEST_FALLBACK


_MANIFEST = read_manifest()


def _manifest_default(*keys: str, fallback: str) -> str:
    node: pyd.JsonValue = _MANIFEST
    for key in keys:
        node = node[key] if isinstance(node, dict) and key in node else None
    return node if isinstance(node, str) else fallback


# New-agent defaults, read from the manifest (the one source) so they aren't restated in code.
DEFAULT_PROVIDER = _manifest_default("default_provider", fallback="claude")
_DEFAULT_PERSONALITY = _manifest_default("default_personality", fallback="dry")
_DEFAULT_CLAUDE_MODEL = _manifest_default("providers", "claude", "default_model", fallback="opus")

# claude-code's assumed window without the 1M beta, and the OpenRouter cap fallback when the user
# hasn't explicitly chosen a context window.
DEFAULT_CONTEXT_WINDOW = 200_000

# The 1M-context beta. build_client_options enables it when the chosen window exceeds the 200k default.
CONTEXT_1M_BETA = "context-1m-2025-08-07"

# Per-provider context bounds enforced by the Field constraints (the catalog's presets live in the manifest).
_CTX_MIN = 1_000
_CLAUDE_CTX_MAX = 1_000_000
_OPENROUTER_CTX_MAX = 200_000

ADAPTIVE_THINKING = ThinkingConfigAdaptive(type="adaptive", display="summarized")


def _resolve_agent_dir() -> pl.Path:
    # Mirrors the agent_dir field, but resolved from env before the config exists so the store path can be located.
    if "AGENT_DIR" in os.environ and os.environ["AGENT_DIR"]:
        return pl.Path(os.environ["AGENT_DIR"]).expanduser().resolve()
    return _DEFAULT_AGENT_DIR


def config_store_path() -> pl.Path:
    """The writable per-agent config store (the nested config, written by PUT /config)."""
    return _resolve_agent_dir() / "data" / "config.json"


def read_config_store() -> dict[str, pyd.JsonValue]:
    """The store's overrides, or {} when absent/corrupt (never raises: it's on the boot path)."""
    path = config_store_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        logger.error(f"config store {path} is corrupt ({exc}); ignoring it")
        return {}
    return data if isinstance(data, dict) else {}


def _write_config_store(data: dict[str, pyd.JsonValue]) -> None:
    path = config_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def update_config_store(updates: dict[str, pyd.JsonValue]) -> None:
    """Merge top-level updates into the store (atomic tmp+rename). A None clears the key; non-field
    keys are rejected. `provider` is replaced wholesale by the caller (deep-merge happens before this
    in the PUT handler); other keys are scalar prefs."""
    fields = VestaConfig.model_fields
    for key in updates:
        if key not in fields:
            raise ValueError(f"{key!r} is not a config field")
    current = read_config_store()
    for key, value in updates.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
    _write_config_store(current)


class ClaudeOAuth(pyd.BaseModel):
    """Mirrors the `claudeAiOauth` blob in the SDK credentials file. Tolerates extra keys: the `claude`
    CLI owns the file and adds fields we don't model. Loaded at boot, never persisted to the store."""

    model_config = pyd.ConfigDict(extra="allow")

    accessToken: str | None = None  # noqa: N815  (mirrors the on-disk camelCase verbatim)
    refreshToken: str | None = None  # noqa: N815
    expiresAt: int | None = None  # noqa: N815


def _read_claude_oauth() -> "ClaudeOAuth | None":
    """The `claudeAiOauth` blob from the SDK credentials file, or None when absent/unreadable. The
    file is the source of truth (the CLI refreshes it in place); we load it into the model at boot but
    never write it back through the config store."""
    if not CREDENTIALS_PATH.is_file():
        return None
    try:
        data = json.loads(CREDENTIALS_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.error(f"credentials file {CREDENTIALS_PATH} unreadable ({exc}); ignoring it")
        return None
    if isinstance(data, dict) and "claudeAiOauth" in data and isinstance(data["claudeAiOauth"], dict):
        return ClaudeOAuth.model_validate(data["claudeAiOauth"])
    return None


# The provider config is a discriminated union by `kind` — it carries the SHAPE invariants (openrouter
# requires a key, claude carries thinking + its OAuth blob), while the catalog of model/context options
# lives in the manifest (reference data). `model` is a free-form slug on both (the picker offers the
# manifest's list; claude-code resolves it), so a typo fails at the SDK, same as openrouter.
class ClaudeConfig(pyd.BaseModel):
    kind: tp.Literal["claude"] = "claude"
    model: str = _DEFAULT_CLAUDE_MODEL
    max_context_tokens: int | None = pyd.Field(default=None, ge=_CTX_MIN, le=_CLAUDE_CTX_MAX)
    thinking: ThinkingConfigAdaptive | ThinkingConfigEnabled | ThinkingConfigDisabled = ADAPTIVE_THINKING
    # Loaded from CREDENTIALS_PATH at construction (see VestaConfig._hydrate_claude_oauth); never persisted.
    oauth: ClaudeOAuth | None = None

    @pyd.field_validator("thinking", mode="before")
    @classmethod
    def _parse_thinking(cls, value: object) -> object:
        return _coerce_thinking(value)


class OpenRouterConfig(pyd.BaseModel):
    kind: tp.Literal["openrouter"] = "openrouter"
    model: str
    max_context_tokens: int | None = pyd.Field(default=None, ge=_CTX_MIN, le=_OPENROUTER_CTX_MAX)
    # SecretStr redacts it in GET /config; client.py injects the real value into the SDK env. Required:
    # an openrouter provider structurally cannot exist without a key. No thinking field (forced disabled).
    key: pyd.SecretStr


Provider = tp.Annotated[ClaudeConfig | OpenRouterConfig, pyd.Field(discriminator="kind")]


def _coerce_thinking(value: object) -> object:
    # The THINKING input may be a plain string (adaptive|enabled|disabled) or the legacy JSON-dict
    # form; coerce both into the SDK's config object, filling now-required fields.
    if isinstance(value, str):
        mode = value.strip().lower()
        if mode in ("", "adaptive"):
            return ThinkingConfigAdaptive(type="adaptive", display="summarized")
        if mode == "enabled":
            return ThinkingConfigEnabled(type="enabled", budget_tokens=_THINKING_ENABLED_BUDGET_TOKENS)
        if mode == "disabled":
            return ThinkingConfigDisabled(type="disabled")
        raise ValueError(f"THINKING must be adaptive|enabled|disabled (or a JSON config object), got {value!r}")
    if isinstance(value, dict):
        # Fill the now-required fields a legacy JSON-dict form may lack, then hand the dict to pydantic
        # to validate into the ThinkingConfig union (no manual reconstruction needed).
        coerced = dict(value)
        kind = str(coerced["type"]).strip().lower() if "type" in coerced else "adaptive"
        if kind == "adaptive" and "display" not in coerced:
            coerced["display"] = "summarized"
        if kind == "enabled" and "budget_tokens" not in coerced:
            coerced["budget_tokens"] = _THINKING_ENABLED_BUDGET_TOKENS
        return coerced
    return value


class VestaConfig(pyd_settings.BaseSettings):
    """Vesta agent configuration: one central config.json (nested), per-agent.

    The active provider (model + context + credential) is a discriminated union under `provider`; the
    rest are provider-independent prefs. Defaults are this model's field defaults (the manifest is the
    generated projection of them). The store wins over env; see settings_customise_sources.

    Key env overrides (operational scalars only; provider fields live in the nested store, not env):
        LOG_LEVEL                - DEBUG | INFO | WARNING | ERROR (default: "INFO")
        PROACTIVE_CHECK_INTERVAL - seconds between proactive checks (default: 60)
        NIGHTLY_MEMORY_HOUR      - hour 0-23 for nightly dream, unset to disable (default: 3)
        RESPONSE_TIMEOUT         - max seconds for a single response (default: 600)
    """

    model_config = pyd_settings.SettingsConfigDict(extra="ignore", populate_by_name=True)

    # None means no provider chosen yet (fresh agent, or signed out) — distinct from a chosen provider
    # whose credential is missing/expired. A concrete provider always reflects an explicit choice.
    provider: Provider | None = None
    agent_personality: str = _DEFAULT_PERSONALITY

    ephemeral: bool = False
    log_level: tp.Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    monitor_tick_interval: int = pyd.Field(default=2, ge=1)
    proactive_check_interval: int = pyd.Field(default=60, ge=1)
    query_timeout: int = pyd.Field(default=120, ge=1)
    response_timeout: int = pyd.Field(default=600, ge=1)
    nightly_memory_hour: int | None = pyd.Field(default=3, ge=0, le=23)
    interrupt_timeout: float = pyd.Field(default=5.0, gt=0)
    ws_port: int = 0
    # SecretStr so it's redacted in GET /config dumps; the auth middleware reads its real value.
    agent_token: pyd.SecretStr | None = None
    agent_dir: pl.Path = pyd.Field(default=_DEFAULT_AGENT_DIR)
    agent_name: str = "vesta"
    # IANA timezone, owned here (not env): clients deliver it via PUT /config. The TZ alias lets a
    # legacy agent seed the field so _apply_timezone re-exports its real value.
    timezone: str = pyd.Field(default="UTC", validation_alias=pyd.AliasChoices("timezone", "TZ"))
    # One-shot freeform setup notes; materialized to data/seed-context.md on boot, read once at first wake.
    seed_context: str = pyd.Field(default="")

    @pyd.model_validator(mode="after")
    def _hydrate_claude_oauth(self) -> "VestaConfig":
        # The store never persists the Claude OAuth blob (the SDK CLI owns/refreshes that file), so a
        # claude provider arrives with oauth=None; load it from disk here. The one non-store injection.
        if isinstance(self.provider, ClaudeConfig) and self.provider.oauth is None:
            self.provider = self.provider.model_copy(update={"oauth": _read_claude_oauth()})
        return self

    @pyd.field_validator("agent_dir", mode="before")
    @classmethod
    def _normalize_agent_dir(cls, value: pl.Path | str | None) -> pl.Path:
        if value is None or value == "":
            return _DEFAULT_AGENT_DIR
        return pl.Path(value).expanduser().resolve()

    @property
    def notifications_dir(self) -> pl.Path:
        return self.agent_dir / "notifications"

    @property
    def data_dir(self) -> pl.Path:
        return self.agent_dir / "data"

    @property
    def logs_dir(self) -> pl.Path:
        return self.agent_dir / "logs"

    @property
    def skills_dir(self) -> pl.Path:
        return self.agent_dir / "skills"

    @property
    def core_prompts_dir(self) -> pl.Path:
        return self.agent_dir / "core" / "prompts"

    @property
    def dreamer_dir(self) -> pl.Path:
        return self.agent_dir / "dreamer"

    @pyd.model_validator(mode="after")
    def _apply_timezone(self) -> "VestaConfig":
        # The config object owns timezone, so applying it to the process env on construction means
        # every consumer (shell `date`, calendar/reminders skills, tasks' tzlocal) inherits it.
        os.environ["TZ"] = self.timezone
        time.tzset()
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[pyd_settings.BaseSettings],
        init_settings: pyd_settings.PydanticBaseSettingsSource,
        env_settings: pyd_settings.PydanticBaseSettingsSource,
        dotenv_settings: pyd_settings.PydanticBaseSettingsSource,
        file_secret_settings: pyd_settings.PydanticBaseSettingsSource,
    ) -> tuple[pyd_settings.PydanticBaseSettingsSource, ...]:
        # Precedence high -> low: init args, config store (PUT /config), env (operational scalars only;
        # provider lives in the store, not env). Defaults come from the model's field defaults.
        sources: list[pyd_settings.PydanticBaseSettingsSource] = [init_settings]
        store = config_store_path()
        if store.is_file():
            try:
                json.loads(store.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                logger.error(f"config store {store} unreadable ({exc}); ignoring it")
            else:
                sources.append(pyd_settings.JsonConfigSettingsSource(settings_cls, json_file=store))
        sources.extend([env_settings, dotenv_settings, file_secret_settings])
        return tuple(sources)


def merge_provider(config: "VestaConfig", patch: dict[str, pyd.JsonValue]) -> dict[str, pyd.JsonValue]:
    """Merge a partial provider onto the current stored provider (which holds the real key), so a
    same-kind patch keeps the rest (a model-only change keeps the key; a re-auth keeps model/context/
    thinking) while a kind switch replaces wholesale. The single merge for both PATCH and sign-in."""
    store = read_config_store()
    if "provider" in store and isinstance(store["provider"], dict):
        current = store["provider"]
    elif config.provider is not None:
        current = {"kind": config.provider.kind}
    else:
        current = {}  # no provider chosen yet; a sign-in patch carries its own kind
    current = tp.cast("dict[str, pyd.JsonValue]", current)
    if "kind" in patch and ("kind" not in current or current["kind"] != patch["kind"]):
        return dict(patch)
    merged = dict(current)
    merged.update(patch)
    merged.pop("oauth", None)
    return merged


def stored_config(config: "VestaConfig") -> dict[str, pyd.JsonValue]:
    """The current config as the wire shows it: nested provider (no oauth, key redacted by SecretStr) +
    scalar prefs. The base for GET /config and GET /provider."""
    data = config.model_dump(mode="json")
    if isinstance(data["provider"], dict):
        data["provider"].pop("oauth", None)
    return data


def validate_config_updates(config: "VestaConfig", data: object) -> dict[str, pyd.JsonValue]:
    """Validate a PUT /config (prefs) or PATCH/sign-in `provider` partial and return the to-write
    top-level dict. A `provider` partial is merged onto the current stored provider (see merge_provider)
    then the whole config is re-validated, so every constraint holds. `oauth` is never accepted here."""
    if not isinstance(data, dict):
        raise ValueError("config body must be a JSON object")
    data = tp.cast("dict[str, pyd.JsonValue]", data)  # narrowed by the isinstance above
    unknown = [key for key in data if key not in VestaConfig.model_fields]
    if unknown:
        raise ValueError(f"not config fields: {', '.join(sorted(unknown))}")
    candidate = stored_config(config)
    updates: dict[str, pyd.JsonValue] = {}
    for key, value in data.items():
        if key == "provider" and isinstance(value, dict):
            merged = merge_provider(config, tp.cast("dict[str, pyd.JsonValue]", value))
            candidate["provider"] = merged
            updates["provider"] = merged
        else:
            candidate[key] = value
            updates[key] = value
    VestaConfig.model_validate(copy.deepcopy(candidate))
    return updates


def load_config() -> tuple[VestaConfig, list[str]]:
    """Build VestaConfig without ever raising.

    Config is on the container's boot path: an exception here exits the process, and with
    `--restart=unless-stopped` that becomes a tight crash loop. So drop each offending env override and
    rebuild, reverting only that field; if nothing is droppable, fall back to a default claude provider.

    Legacy convergence runs first (before the config is built), so the loaded config reflects the
    migrated nested provider rather than a stale default. This makes load_config the single owner of
    "what config does the agent run on" — there is no separate boot step to sequence wrongly.
    """
    migrate_legacy_config_to_store()
    issues: list[str] = []
    dropped: set[str] = set()
    while True:
        try:
            return VestaConfig(), issues
        except pyd.ValidationError as exc:
            progressed = False
            for error in exc.errors():
                loc = error["loc"]
                if not loc:
                    continue
                # Only operational scalars come from env (provider lives in the store, not env), so the
                # offending var is the top-level field name uppercased.
                env_name = str(loc[0]).upper()
                if env_name in os.environ and env_name not in dropped:
                    issues.append(f"{env_name}={os.environ[env_name]!r} is invalid ({error['msg']}); reverted to default")
                    del os.environ[env_name]
                    dropped.add(env_name)
                    progressed = True
            if not progressed:
                # Bad store value or invalid field default: fall back to a default claude provider
                # rather than crash-loop. model_construct skips validators, so build provider by hand
                # and preserve the agent token from env so the HTTP/WS API stays authenticated.
                issues.append(f"configuration could not be validated, using all defaults: {exc}")
                token = os.environ["AGENT_TOKEN"] if "AGENT_TOKEN" in os.environ and os.environ["AGENT_TOKEN"] else None
                return (
                    VestaConfig.model_construct(
                        provider=ClaudeConfig(oauth=_read_claude_oauth()),
                        agent_token=pyd.SecretStr(token) if token is not None else None,
                    ),
                    issues,
                )


_LEGACY_PROVIDER_ENV = pl.Path.home() / ".claude" / "vesta-provider.env"
_LEGACY_FLAT_KEYS = ("agent_model", "agent_provider", "openrouter_key", "max_context_tokens", "thinking")


def _parse_legacy_export(content: str, key: str) -> str | None:
    """Read a `[export ]KEY=value` line from a shell env file, unquoting once; None if absent/empty."""
    for raw_line in content.splitlines():
        line = raw_line.strip().removeprefix("export ")
        name, _, value = line.partition("=")
        if "=" not in line or name.strip() != key:
            continue
        value = value.strip()
        if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        return value or None
    return None


def migrate_legacy_config_to_store() -> None:
    """Relocate a legacy agent's flat provider config into the nested `provider` object, draining the
    old flat config.json keys, the legacy env vars, and vesta-provider.env. Idempotent: once the store
    has a `provider` and no flat keys, it's a no-op. This is the only place flat->nested lives.

    LEGACY(remove-when: no fleet agent boots with flat provider keys in config.json): this function,
    its boot call site, _parse_legacy_export, and _LEGACY_FLAT_KEYS.
    """
    store = read_config_store()
    content = _LEGACY_PROVIDER_ENV.read_text() if _LEGACY_PROVIDER_ENV.is_file() else ""
    changed = False

    def legacy(env_key: str, store_key: str) -> str | None:  # old flat store key wins, then env, then file
        if store_key in store and store[store_key] not in (None, ""):
            return str(store[store_key])
        env = os.environ[env_key] if env_key in os.environ else ""
        return env or _parse_legacy_export(content, env_key)

    if "provider" not in store:
        kind = legacy("AGENT_PROVIDER", "agent_provider")
        model = legacy("AGENT_MODEL", "agent_model")
        key = legacy("ANTHROPIC_AUTH_TOKEN", "openrouter_key")
        ctx_raw = legacy("MAX_CONTEXT_TOKENS", "max_context_tokens")
        ctx = int(ctx_raw) if ctx_raw and ctx_raw.isdigit() else None
        provider: dict[str, pyd.JsonValue] | None = None
        if kind == "openrouter" and key and model:
            provider = {"kind": "openrouter", "model": model, "key": key}
            if ctx is not None:
                provider["max_context_tokens"] = ctx
        elif model or kind == "claude":
            provider = {"kind": "claude", "model": model or "opus"}
            if ctx is not None:
                provider["max_context_tokens"] = ctx
            if "thinking" in store and store["thinking"] is not None:
                provider["thinking"] = store["thinking"]
        if provider is not None:
            store["provider"] = provider
            changed = True

    for flat in _LEGACY_FLAT_KEYS:
        if flat in store:
            store.pop(flat, None)
            changed = True

    personality = os.environ["AGENT_PERSONALITY"] if "AGENT_PERSONALITY" in os.environ else _parse_legacy_export(content, "AGENT_PERSONALITY")
    if personality and "agent_personality" not in store:
        store["agent_personality"] = personality
        changed = True
    tz = os.environ["TZ"] if "TZ" in os.environ else None
    if tz and tz != "UTC" and "timezone" not in store:
        store["timezone"] = tz
        changed = True

    if changed:
        logger.startup("migrated legacy flat config into the nested provider store")
        _write_config_store(store)
    _LEGACY_PROVIDER_ENV.unlink(missing_ok=True)
