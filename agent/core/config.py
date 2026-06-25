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

# Shipped new-agent defaults, read here as the config floor and by vestad (from the embedded agent
# source) for GET /agent-defaults, so they live in one place across Python and Rust.
CONFIG_DEFAULTS_PATH = pl.Path(__file__).parent / "defaults.json"


def _resolve_agent_dir() -> pl.Path:
    # Mirrors the agent_dir field, but resolved from env before the config exists so the store path can be located.
    if "AGENT_DIR" in os.environ and os.environ["AGENT_DIR"]:
        return pl.Path(os.environ["AGENT_DIR"]).expanduser().resolve()
    return _DEFAULT_AGENT_DIR


def config_store_path() -> pl.Path:
    """The writable per-agent config store (sparse overrides written by PUT /config)."""
    return _resolve_agent_dir() / "data" / "config.json"


def read_config_store() -> dict[str, tp.Any]:
    """The store's sparse overrides, or {} when absent/corrupt (never raises: it's on the boot path)."""
    path = config_store_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        logger.error(f"config store {path} is corrupt ({exc}); ignoring it")
        return {}
    return data if isinstance(data, dict) else {}


def update_config_store(updates: dict[str, tp.Any]) -> None:
    """Merge updates into the store (atomic tmp+rename). A None clears the key; non-field keys are rejected."""
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
    path = config_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(current, indent=2))
    tmp.replace(path)


# PROVIDER_PREF_FIELDS names the preferences that are tied to the provider/account lifecycle: they
# are wiped on sign-out (clear_provider) because a new account may not offer the same model, while
# general config (personality, timezone, ...) survives. They are still set through the generic PUT
# /config like any other preference — this set exists only for the sign-out wipe, not for routing.
# The auth fields are written only by provider.py's set_claude/set_openrouter/clear_provider and are
# rejected by PUT /config (they carry credential-file + provider-status side effects).
PROVIDER_PREF_FIELDS = frozenset({"agent_model", "max_context_tokens", "thinking"})
_PROVIDER_AUTH_FIELDS = frozenset({"agent_provider", "openrouter_key"})


def _merge_validate(config: "VestaConfig", data: dict[str, tp.Any]) -> dict[str, tp.Any]:
    """Merge a sparse update onto the live config and validate the whole model, so each field is
    checked under its real constraints (thinking coerces, gt/le hold). A null clears its key."""
    unknown = [key for key in data if key not in VestaConfig.model_fields]
    if unknown:
        raise ValueError(f"not config fields: {', '.join(sorted(unknown))}")
    candidate = config.model_dump()
    candidate.update({key: value for key, value in data.items() if value is not None})
    VestaConfig.model_validate(candidate)
    return data


def validate_config_updates(config: "VestaConfig", data: object) -> dict[str, tp.Any]:
    """Validate a sparse PUT /config body. Every agent preference is settable here — model, context,
    thinking, personality, timezone, seed_context — since they all live in one config store. The
    derived auth fields (provider choice + OpenRouter key) are rejected: provider credentials are set
    via PUT /config/auth and cleared via DELETE /config/auth, which own the credential files and the
    derived status. PROVIDER_PREF_FIELDS still names the model/context/thinking subset, but only for
    clear_provider's sign-out wipe, not for routing."""
    if not isinstance(data, dict):
        raise ValueError("config body must be a JSON object")
    data = tp.cast("dict[str, tp.Any]", data)
    auth_owned = sorted(set(data) & _PROVIDER_AUTH_FIELDS)
    if auth_owned:
        raise ValueError(f"auth-owned, set via PUT /config/auth or DELETE /config/auth: {', '.join(auth_owned)}")
    return _merge_validate(config, data)


_LEGACY_PROVIDER_ENV = pl.Path.home() / ".claude" / "vesta-provider.env"


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
    """Drain a legacy agent's preferences (env) and provider choice/key (old vesta-provider.env, then
    deleted) into the store, seeding only unset keys. Idempotent.

    LEGACY(remove-when: every fleet agent has a config.json and no vesta-provider.env): this function,
    its boot call site, and the env layer in settings_customise_sources.
    """
    store = read_config_store()
    content = _LEGACY_PROVIDER_ENV.read_text() if _LEGACY_PROVIDER_ENV.is_file() else ""

    def legacy(key: str) -> str | None:  # env wins over the old provider file
        return (os.environ[key] if key in os.environ else "") or _parse_legacy_export(content, key)

    provider = legacy("AGENT_PROVIDER")
    ctx = legacy("MAX_CONTEXT_TOKENS")
    candidates: dict[str, tp.Any] = {
        "agent_model": legacy("AGENT_MODEL"),
        "agent_personality": legacy("AGENT_PERSONALITY"),
        "agent_provider": provider if provider in ("claude", "openrouter") else None,
        "openrouter_key": legacy("ANTHROPIC_AUTH_TOKEN") if provider == "openrouter" else None,
        "max_context_tokens": int(ctx) if ctx and ctx.isdigit() else None,
        # Fleet agents created before timezone moved into the store carry it as the TZ env var
        # (from /run/vestad-env or ~/.bashrc); drain a real value into the store so it owns it. UTC
        # is the default floor, so there's nothing to converge (and skipping it keeps a fresh agent's
        # store clean until the client delivers the real tz).
        "timezone": tz if (tz := legacy("TZ")) and tz != "UTC" else None,
    }
    updates = {key: value for key, value in candidates.items() if value is not None and key not in store}
    if updates:
        logger.startup(f"migrated legacy config into the store: {sorted(updates)}")
        update_config_store(updates)
    _LEGACY_PROVIDER_ENV.unlink(missing_ok=True)


# claude-code's assumed window without the 1M beta, and the OpenRouter cap fallback
# when the user hasn't explicitly chosen a context window.
DEFAULT_CONTEXT_WINDOW = 200_000

# The 1M-context beta. build_client_options enables it when the chosen window exceeds the 200k
# default; the official client's get_context_usage() then reports usage against the CLI's enforced
# window, so no model-specific window constant is passed across the SDK seam.
CONTEXT_1M_BETA = "context-1m-2025-08-07"


class VestaConfig(pyd_settings.BaseSettings):
    """Vesta agent configuration.

    Every field can be overridden via env var (uppercased field name, no prefix).
    Set in ~/.bashrc and run restart_vesta to apply.

    Defaults come from the shipped defaults.json; the writable config store (~/agent/data/config.json,
    PUT /config) overrides them and wins over env. See settings_customise_sources.

    Key overrides:
        AGENT_MODEL   - model name, e.g. "sonnet", "opus", "haiku" (config-store preference;
                        default from defaults.json)
        AGENT_NAME    - agent name (default: "vesta")
        AGENT_PROVIDER - "claude" (OAuth) or "openrouter" (API key); set by /provider, default from defaults.json
        LOG_LEVEL     - DEBUG | INFO | WARNING | ERROR (default: "INFO")
        THINKING      - adaptive | enabled | disabled (default: "adaptive")
        PROACTIVE_CHECK_INTERVAL - seconds between proactive checks (default: 60)
        NIGHTLY_MEMORY_HOUR      - hour 0-23 for nightly dream, unset to disable (default: 3)
        RESPONSE_TIMEOUT         - max seconds for a single response (default: 600)
        MAX_CONTEXT_TOKENS       - context window passed to claude-code. Claude: caps the
                                   autocompact threshold and requests the 1M beta when above
                                   200k; unset = model default (1M for Claude). OpenRouter:
                                   caps the model's real window (fallback cap 200000 when
                                   unset). Smaller = cheaper prompt-cache reads.
    """

    model_config = pyd_settings.SettingsConfigDict(extra="ignore", populate_by_name=True)

    ephemeral: bool = False
    log_level: tp.Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    monitor_tick_interval: int = pyd.Field(default=2, ge=1)
    proactive_check_interval: int = pyd.Field(default=60, ge=1)
    query_timeout: int = pyd.Field(default=120, ge=1)
    response_timeout: int = pyd.Field(default=600, ge=1)
    max_context_tokens: int | None = pyd.Field(default=None, ge=1)
    nightly_memory_hour: int | None = pyd.Field(default=3, ge=0, le=23)
    interrupt_timeout: float = pyd.Field(default=5.0, gt=0)
    thinking: ThinkingConfigAdaptive | ThinkingConfigEnabled | ThinkingConfigDisabled = ThinkingConfigAdaptive(
        type="adaptive", display="summarized"
    )
    ws_port: int = 0
    # SecretStr so it's redacted in GET /config dumps; the auth middleware reads its real value.
    agent_token: pyd.SecretStr | None = None

    agent_dir: pl.Path = pyd.Field(default=_DEFAULT_AGENT_DIR)

    @pyd.field_validator("thinking", mode="before")
    @classmethod
    def _parse_thinking(cls, value: object) -> object:
        # The THINKING env var is documented as a plain string (adaptive|enabled|disabled);
        # coerce it into the SDK's config dict.
        if isinstance(value, str):
            mode = value.strip().lower()
            if mode in ("", "adaptive"):
                return ThinkingConfigAdaptive(type="adaptive", display="summarized")
            if mode == "enabled":
                return ThinkingConfigEnabled(type="enabled", budget_tokens=_THINKING_ENABLED_BUDGET_TOKENS)
            if mode == "disabled":
                return ThinkingConfigDisabled(type="disabled")
            raise ValueError(f"THINKING must be adaptive|enabled|disabled (or a JSON config object), got {value!r}")
        # Legacy env files set the JSON-dict form (e.g. THINKING='{"type":"adaptive"}'), which
        # predates the now-required fields (adaptive.display). Fill in the same defaults the
        # string form uses so an upgrade doesn't fail union validation. Unknown types fall
        # through to pydantic's normal error.
        if isinstance(value, dict):
            data = tp.cast("dict[str, tp.Any]", value)
            kind = str(data["type"]).strip().lower() if "type" in data else "adaptive"
            if kind == "adaptive":
                return ThinkingConfigAdaptive(type="adaptive", display=data["display"] if "display" in data else "summarized")
            if kind == "enabled":
                return ThinkingConfigEnabled(
                    type="enabled", budget_tokens=data["budget_tokens"] if "budget_tokens" in data else _THINKING_ENABLED_BUDGET_TOKENS
                )
            if kind == "disabled":
                return ThinkingConfigDisabled(type="disabled")
        return value

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

    agent_name: str = "vesta"
    # init=False: these come from the layered sources (store > env > defaults.json floor), never init args.
    agent_model: str = pyd.Field(init=False)
    agent_provider: tp.Literal["claude", "openrouter"] = pyd.Field(init=False)
    agent_personality: str = pyd.Field(init=False)
    # None for Claude. SecretStr redacts it in GET /config; client.py injects the real value into the SDK env.
    openrouter_key: pyd.SecretStr | None = None
    # IANA timezone, owned here (not env): clients deliver it via PUT /config at provision time, the
    # timezone skill changes it the same way. _apply_timezone below pushes it into the process env.
    # The TZ alias lets a legacy agent (TZ still in /run/vestad-env or ~/.bashrc) seed the field, so
    # _apply_timezone re-exports its real value instead of clobbering it with the UTC default.
    timezone: str = pyd.Field(default="UTC", validation_alias=pyd.AliasChoices("timezone", "TZ"))
    # One-shot freeform setup notes from whoever created the agent. Delivered via PUT /config; the
    # agent materializes it to data/seed-context.md on boot and reads it once at first wake.
    seed_context: str = pyd.Field(default="")

    @pyd.model_validator(mode="after")
    def _apply_timezone(self) -> "VestaConfig":
        # The config object owns timezone, so applying it to the process env on construction means
        # every consumer (shell `date`, the calendar/reminders skills, tasks' tzlocal) inherits it,
        # and a PUT /config change just takes effect on the next boot with no separate mechanism.
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
        # Precedence high -> low: init args, config store (PUT /config wins over a stale env), env, defaults floor.
        sources: list[pyd_settings.PydanticBaseSettingsSource] = [init_settings]
        store = config_store_path()
        # Layer the store in only when it parses; a corrupt store falls back to env/defaults instead of
        # crashing the boot (JsonConfigSettingsSource raises on malformed JSON).
        if store.is_file():
            try:
                json.loads(store.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                logger.error(f"config store {store} unreadable ({exc}); ignoring it")
            else:
                sources.append(pyd_settings.JsonConfigSettingsSource(settings_cls, json_file=store))
        # LEGACY(remove-when: every fleet agent has a config.json): env as a source of store preferences,
        # for agents that predate the store.
        sources.extend([env_settings, dotenv_settings, file_secret_settings])
        sources.append(pyd_settings.JsonConfigSettingsSource(settings_cls, json_file=CONFIG_DEFAULTS_PATH))
        return tuple(sources)


def load_config() -> tuple[VestaConfig, list[str]]:
    """Build VestaConfig without ever raising.

    Config is on the container's boot path: an exception here exits the process, and with
    `--restart=unless-stopped` that becomes a tight crash loop the agent can never escape.
    So instead of letting a single malformed env override (e.g. a stale THINKING or a
    non-numeric RESPONSE_TIMEOUT in ~/.bashrc) kill startup, drop each offending var from the
    environment and rebuild, reverting only that field to its default. Returns the config plus
    a human-readable message per reverted var so the caller can surface them to the agent.
    """
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
                env_name = str(loc[0]).upper()
                if env_name in os.environ and env_name not in dropped:
                    issues.append(f"{env_name}={os.environ[env_name]!r} is invalid ({error['msg']}); reverted to default")
                    del os.environ[env_name]
                    dropped.add(env_name)
                    progressed = True
            if not progressed:
                # No env var to drop (bad store value or invalid field default). Fall back to defaults
                # rather than crash-loop; seed the shipped floor so the init=False fields are populated.
                issues.append(f"configuration could not be validated, using all defaults: {exc}")
                return VestaConfig.model_construct(**json.loads(CONFIG_DEFAULTS_PATH.read_text())), issues
