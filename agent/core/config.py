import copy
import json
import os
import pathlib as pl
import re
import time
import typing as tp

import annotated_types as at
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

# The generated provider/defaults manifest (catalog + defaults). It is the model's projection for the
# non-Python layers (vestad serves it, web/cli read it); regenerate with agent/generate-manifest.py.
MANIFEST_PATH = pl.Path(__file__).parent / "manifest.json"

# claude-code's assumed window without the 1M beta, and the OpenRouter cap fallback when the user
# hasn't explicitly chosen a context window.
DEFAULT_CONTEXT_WINDOW = 200_000

# The 1M-context beta. build_client_options enables it when the chosen window exceeds the 200k default.
CONTEXT_1M_BETA = "context-1m-2025-08-07"

# Per-provider context bounds: one constant each, reused by the Field constraints (the single source;
# the manifest generator reads them back off the fields, never restating them).
_CTX_MIN = 1_000
_CLAUDE_CTX_MAX = 1_000_000
_OPENROUTER_CTX_MAX = 200_000

DEFAULT_PROVIDER = "claude"
ADAPTIVE_THINKING = ThinkingConfigAdaptive(type="adaptive", display="summarized")

# Shipped personality skill presets (frontmatter catalog folded into the manifest). Relative to this
# module, agent/core/ -> agent/skills/...; the same path resolves in the container (~/agent/skills).
_PRESETS_DIR = pl.Path(__file__).parent.parent / "skills" / "personality" / "presets"
_PRESET_ORDER_LAST = 2**31


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


class ContextPreset(pyd.BaseModel):
    """A curated context-window suggestion shown in the picker. The first preset is the UI default."""

    tokens: int
    label: str
    note: str


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


class ClaudeConfig(pyd.BaseModel):
    kind: tp.Literal["claude"] = "claude"
    model: tp.Literal["opus", "sonnet", "haiku"] = "opus"
    max_context_tokens: int | None = pyd.Field(default=None, ge=_CTX_MIN, le=_CLAUDE_CTX_MAX)
    thinking: ThinkingConfigAdaptive | ThinkingConfigEnabled | ThinkingConfigDisabled = ADAPTIVE_THINKING
    # Loaded from CREDENTIALS_PATH at construction (see VestaConfig._hydrate_claude_oauth); never persisted.
    oauth: ClaudeOAuth | None = None

    # The only two presentation bits the type system can't express, as plain ClassVars (the manifest's
    # one source; everything else the manifest needs is derived from the fields above).
    display: tp.ClassVar[str] = "Claude account"
    context_presets: tp.ClassVar[list[ContextPreset]] = [
        ContextPreset(tokens=1_000_000, label="1M", note="most context"),
        ContextPreset(tokens=500_000, label="500K", note="balanced"),
        ContextPreset(tokens=200_000, label="200K", note="cheapest prompt-cache reads, compacts soonest"),
    ]

    @pyd.field_validator("thinking", mode="before")
    @classmethod
    def _parse_thinking(cls, value: object) -> object:
        return _coerce_thinking(value)


class OpenRouterConfig(pyd.BaseModel):
    kind: tp.Literal["openrouter"] = "openrouter"
    model: str
    max_context_tokens: int | None = pyd.Field(default=None, ge=_CTX_MIN, le=_OPENROUTER_CTX_MAX)
    # SecretStr redacts it in GET /config; client.py injects the real value into the SDK env. Required:
    # an openrouter provider structurally cannot exist without a key.
    key: pyd.SecretStr
    # No thinking field: openrouter can't set it (runtime forces disabled). The manifest derives
    # thinking_supported from the absence of this field.

    display: tp.ClassVar[str] = "OpenRouter"
    context_presets: tp.ClassVar[list[ContextPreset]] = [
        ContextPreset(tokens=200_000, label="200K", note="full window"),
        ContextPreset(tokens=128_000, label="128K", note="balanced"),
        ContextPreset(tokens=64_000, label="64K", note="cheapest prompt-cache reads"),
    ]


Provider = tp.Annotated[ClaudeConfig | OpenRouterConfig, pyd.Field(discriminator="kind")]
_ProviderClass = type[ClaudeConfig] | type[OpenRouterConfig]
_PROVIDER_CLASSES: tuple[_ProviderClass, ...] = (ClaudeConfig, OpenRouterConfig)


class ContextSpec(pyd.BaseModel):
    min: int
    max: int
    default: int
    presets: list[ContextPreset]


class ProviderEntry(pyd.BaseModel):
    kind: str
    display: str
    models: list[str] | tp.Literal["live"]  # explicit slugs (claude) or "live" (openrouter, fetched)
    default_model: str | None
    thinking_supported: bool
    context: ContextSpec


class PersonalityPreset(pyd.BaseModel):
    name: str
    emoji: str = ""
    title: str = ""
    description: str = ""
    sample: str = ""
    order: int = _PRESET_ORDER_LAST


class Manifest(pyd.BaseModel):
    """The whole new-agent setup description, generated from the agent's models + shipped skills: every
    settable pref's default (generic over the fields), the per-provider catalog, and the personality
    presets. One document the wizard/settings read, so nothing is hand-picked or kept on a side endpoint."""

    default_provider: str
    prefs: dict[str, pyd.JsonValue]
    providers: dict[str, ProviderEntry]
    personalities: list[PersonalityPreset]


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


def _ctx_bound(cls: _ProviderClass, *, want_min: bool) -> int:
    """Read a context-window bound (annotated_types.Ge / Le) off the field metadata, so the manifest
    never restates a bound the Field already owns."""
    for meta in cls.model_fields["max_context_tokens"].metadata:
        if want_min and isinstance(meta, at.Ge):
            return int(meta.ge)
        if not want_min and isinstance(meta, at.Le):
            return int(meta.le)
    return _CTX_MIN if want_min else _CLAUDE_CTX_MAX


def _provider_manifest_entry(cls: _ProviderClass) -> ProviderEntry:
    """One manifest entry, derived entirely from a provider class: catalog ClassVars + field metadata.
    Nothing is restated (bounds, default model, thinking support all come from the fields)."""
    args = tp.get_args(cls.model_fields["model"].annotation)
    models: list[str] | tp.Literal["live"] = [str(arg) for arg in args] if args else "live"
    default = cls.model_fields["model"].default
    presets = cls.context_presets
    return ProviderEntry(
        kind=str(cls.model_fields["kind"].default),
        display=cls.display,
        models=models,
        default_model=default if isinstance(default, str) else None,
        thinking_supported="thinking" in cls.model_fields,
        context=ContextSpec(
            min=_ctx_bound(cls, want_min=True), max=_ctx_bound(cls, want_min=False), default=presets[0].tokens, presets=presets
        ),
    )


def _frontmatter_field(fields: dict[str, str], key: str) -> str:
    return fields[key].strip().strip('"') if key in fields else ""


def read_personalities() -> list[PersonalityPreset]:
    """Parse the shipped personality skill presets (frontmatter) into catalog entries, sorted by their
    declared order. Folded into the manifest so the setup wizard reads one document, not a side endpoint."""
    presets: list[PersonalityPreset] = []
    if not _PRESETS_DIR.is_dir():
        return presets
    for md in sorted(_PRESETS_DIR.glob("*.md")):
        match = re.match(r"^---\n(.*?)\n---", md.read_text(), re.DOTALL)
        fields = dict(re.findall(r"^(\w+)\s*:\s*(.+)$", match.group(1), re.MULTILINE)) if match else {}
        order = _frontmatter_field(fields, "order")
        presets.append(
            PersonalityPreset(
                name=md.stem,
                emoji=_frontmatter_field(fields, "emoji"),
                title=_frontmatter_field(fields, "title"),
                description=_frontmatter_field(fields, "description"),
                sample=_frontmatter_field(fields, "sample"),
                order=int(order) if order.isdigit() else _PRESET_ORDER_LAST,
            )
        )
    return sorted(presets, key=lambda preset: preset.order)


def build_manifest() -> Manifest:
    """The whole-config manifest, generated from the models + shipped skills. `prefs` is every settable
    scalar field's default, derived generically (no hand-picked subset); `providers` is the per-provider
    catalog; `personalities` is the shipped preset catalog. generate-manifest.py writes it; CI checks it."""
    prefs: dict[str, pyd.JsonValue] = {
        name: field.default
        for name, field in VestaConfig.model_fields.items()
        if isinstance(field.default, (str, int, float)) or field.default is None
    }
    entries = [_provider_manifest_entry(cls) for cls in _PROVIDER_CLASSES]
    return Manifest(
        default_provider=DEFAULT_PROVIDER,
        prefs=prefs,
        providers={entry.kind: entry for entry in entries},
        personalities=read_personalities(),
    )


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

    provider: Provider = pyd.Field(default_factory=ClaudeConfig)
    agent_personality: str = "dry"

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


def _provider_patch(current: dict[str, pyd.JsonValue], patch: dict[str, pyd.JsonValue]) -> dict[str, pyd.JsonValue]:
    """Deep-merge a partial provider (model / context / thinking) onto the current stored provider, so
    a PATCH that omits the key keeps the stored key and the rest."""
    merged = dict(current)
    merged.update(patch)
    return merged


def stored_config(config: "VestaConfig", *, redact: bool = True) -> dict[str, pyd.JsonValue]:
    """The current config as the store persists it: nested provider (no oauth) + scalar prefs. With
    redact=True (the wire default) the openrouter key shows as SecretStr's '**********'; with
    redact=False the real key is restored, for use as a deep-merge base that must round-trip it."""
    data = config.model_dump(mode="json")
    provider = data["provider"]
    if isinstance(provider, dict):
        provider.pop("oauth", None)
        if not redact and isinstance(config.provider, OpenRouterConfig):
            provider["key"] = config.provider.key.get_secret_value()
    return data


def validate_config_updates(config: "VestaConfig", data: object) -> dict[str, pyd.JsonValue]:
    """Validate a PUT /config (prefs) or PATCH /provider partial against the nested model and return
    the to-write top-level dict. A `provider` partial is deep-merged onto the current provider (with
    the real key, not the redacted dump) then the whole config is re-validated, so every constraint
    holds and a key-omitting patch round-trips the stored key. `oauth` is never accepted here."""
    if not isinstance(data, dict):
        raise ValueError("config body must be a JSON object")
    data = tp.cast("dict[str, pyd.JsonValue]", data)  # narrowed by the isinstance above
    unknown = [key for key in data if key not in VestaConfig.model_fields]
    if unknown:
        raise ValueError(f"not config fields: {', '.join(sorted(unknown))}")
    candidate = stored_config(config, redact=False)
    updates: dict[str, pyd.JsonValue] = {}
    for key, value in data.items():
        if key == "provider" and isinstance(value, dict):
            base = candidate["provider"] if isinstance(candidate["provider"], dict) else {}
            merged = _provider_patch(tp.cast("dict[str, pyd.JsonValue]", base), tp.cast("dict[str, pyd.JsonValue]", value))
            merged.pop("oauth", None)
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
