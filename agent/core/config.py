import contextlib
import copy
import datetime as dt
import json
import os
import pathlib as pl
import re
import tempfile
import threading
import typing as tp
import uuid

import pydantic as pyd
import pydantic_settings as pyd_settings
from claude_agent_sdk.types import SdkBeta, ThinkingConfigAdaptive, ThinkingConfigDisabled, ThinkingConfigEnabled

from core import logger

from .notification_interrupt_policy import NotificationInterruptRule, drop_expired

_DEFAULT_AGENT_DIR = pl.Path.home() / "agent"
_THINKING_ENABLED_BUDGET_TOKENS = 10000
_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CONFIG_WRITE_LOCK = threading.RLock()
_ProviderModel = tp.Annotated[str, pyd.StringConstraints(strip_whitespace=True, min_length=1)]
ProviderKind = tp.Literal["claude", "openrouter", "zai", "kimi", "openai"]
KeyProviderKind = tp.Literal["openrouter", "zai", "kimi"]
ProviderAuthKind = tp.Literal["claude_oauth", "device_oauth", "subscription_key", "api_key"]

# The Claude OAuth blob lives at the SDK-owned path: the `claude` CLI reads AND refreshes it in place,
# so it is never persisted into the config store. Owned here (config.py is the lower-level module);
# provider.py re-exports it.
CREDENTIALS_PATH = pl.Path.home() / ".claude" / ".credentials.json"

# The hand-authored provider/setup catalog + new-agent defaults. It is the single source of that
# reference data: the Python model reads it for its field defaults (below), vestad embeds + serves it at
# GET /manifest (merging in the personality presets), and the web app reads it. No generation step.
MANIFEST_PATH = pl.Path(__file__).parent / "manifest.json"


# A tiny floor so a corrupt/missing manifest can never crash-loop the boot path (it never happens in
# practice; the file ships with the agent).
class _ContextPreset(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="forbid")

    tokens: int = pyd.Field(gt=0)
    label: str = pyd.Field(min_length=1)
    note: str = pyd.Field(min_length=1)
    plans: list[str] | None = None


class _ContextPolicy(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="forbid")

    default: int = pyd.Field(ge=0)
    max: int | None = pyd.Field(default=None, gt=0)
    presets: list[_ContextPreset]
    defaults_by_plan: dict[str, int] | None = None
    harness_suffix_above: int | None = pyd.Field(default=None, ge=0)

    @pyd.model_validator(mode="after")
    def _values_fit_max(self) -> "_ContextPolicy":
        if self.max is None:
            if self.default != 0 or self.presets or self.defaults_by_plan or self.harness_suffix_above is not None:
                raise ValueError("model-reported context cannot declare static context policy")
            return self
        values = [
            self.default,
            *(preset.tokens for preset in self.presets),
            *((self.defaults_by_plan or {}).values()),
        ]
        if any(value > self.max for value in values):
            raise ValueError(f"context default/preset exceeds explicit max {self.max}")
        if self.harness_suffix_above is not None and self.harness_suffix_above >= self.max:
            raise ValueError("harness suffix threshold must be below context max")
        return self


class _ProviderManifestEntry(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="forbid")

    display: str = pyd.Field(min_length=1)
    order: int = pyd.Field(ge=0)
    auth_kind: ProviderAuthKind
    models: list[_ProviderModel] | tp.Literal["live"]
    default_model: _ProviderModel | None
    auxiliary_model: _ProviderModel | None = None
    context: _ContextPolicy
    context_by_model: dict[str, _ContextPolicy] = pyd.Field(default_factory=dict)

    @pyd.model_validator(mode="after")
    def _default_is_selectable(self) -> "_ProviderManifestEntry":
        if self.models == "live":
            if self.default_model is not None:
                raise ValueError("live model catalogs cannot declare a static default")
        elif self.default_model not in self.models:
            raise ValueError("default_model must be present in models")
        if self.auxiliary_model is not None and (not isinstance(self.models, list) or self.auxiliary_model not in self.models):
            raise ValueError("auxiliary_model must be present in fixed models")
        unknown_contexts = set(self.context_by_model) - set(self.models if isinstance(self.models, list) else [])
        if unknown_contexts:
            raise ValueError(f"context_by_model contains unknown models: {sorted(unknown_contexts)}")
        return self


class _ProviderManifest(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="forbid")

    default_provider: ProviderKind
    default_personality: str
    providers: dict[ProviderKind, _ProviderManifestEntry]

    @pyd.model_validator(mode="after")
    def _default_provider_exists(self) -> "_ProviderManifest":
        if self.default_provider not in self.providers:
            raise ValueError("default_provider must be present in providers")
        orders = [entry.order for entry in self.providers.values()]
        if len(orders) != len(set(orders)):
            raise ValueError("provider order values must be unique")
        return self


_MANIFEST_FALLBACK: dict[str, pyd.JsonValue] = {
    "default_provider": "claude",
    "default_personality": "dry",
    "providers": {
        "claude": {
            "display": "Claude account",
            "order": 0,
            "auth_kind": "claude_oauth",
            "models": ["opus"],
            "default_model": "opus",
            "context": {"default": 200_000, "max": 200_000, "presets": []},
        }
    },
}


def _load_manifest() -> _ProviderManifest:
    try:
        return _ProviderManifest.model_validate_json(MANIFEST_PATH.read_text())
    except (OSError, pyd.ValidationError):
        return _ProviderManifest.model_validate(_MANIFEST_FALLBACK)


_MANIFEST_MODEL = _load_manifest()


def read_manifest() -> dict[str, pyd.JsonValue]:
    """Return the validated provider catalog in its JSON wire shape."""
    return tp.cast("dict[str, pyd.JsonValue]", _MANIFEST_MODEL.model_dump(mode="json", exclude_unset=True))


def _provider_model_policy(kind: str, model: str) -> _ContextPolicy | None:
    entry = _MANIFEST_MODEL.providers.get(kind)
    if entry is None:
        return None
    return entry.context_by_model.get(model.removesuffix("[1m]"), entry.context)


def provider_context_default(kind: str, model: str) -> int | None:
    """Return the catalog default for one provider/model; zero means model-reported, so None."""
    policy = _provider_model_policy(kind, model)
    return policy.default if policy is not None and policy.default > 0 else None


def provider_auxiliary_model(kind: ProviderKind) -> str | None:
    """Return the provider's catalog-owned cheap/background model, when one is declared."""
    entry = _MANIFEST_MODEL.providers.get(kind)
    return entry.auxiliary_model if entry is not None else None


def provider_harness_model(kind: ProviderKind, model: str, context: int) -> str:
    """Apply catalog-declared Claude-harness model suffixes without transport constants in code."""
    base_model = model.removesuffix("[1m]")
    policy = _provider_model_policy(kind, base_model)
    if policy is not None and policy.harness_suffix_above is not None and context > policy.harness_suffix_above:
        return f"{base_model}[1m]"
    return base_model


def _validate_catalog_provider(kind: str, model: str, max_context_tokens: int | None) -> None:
    """Enforce the manifest's fixed model catalog and model-specific context ceiling."""
    entry = _MANIFEST_MODEL.providers.get(kind)
    base_model = model.removesuffix("[1m]")
    if entry is None:
        raise ValueError(f"unknown provider {kind}")
    if isinstance(entry.models, list) and base_model not in entry.models:
        raise ValueError(f"{model} is not a supported {kind} model")
    policy = _provider_model_policy(kind, model)
    limit = policy.max if policy is not None else None
    if limit is not None and max_context_tokens is not None and max_context_tokens > limit:
        raise ValueError(f"{model} supports at most {limit} context tokens")


# New-agent defaults, read from the manifest (the one source) so they aren't restated in code.
DEFAULT_PROVIDER = _MANIFEST_MODEL.default_provider
_DEFAULT_PERSONALITY = _MANIFEST_MODEL.default_personality
_DEFAULT_CLAUDE_MODEL = _MANIFEST_MODEL.providers["claude"].default_model or "opus"

# claude-code's assumed window without the 1M beta, and the OpenRouter cap fallback when the user
# hasn't explicitly chosen a context window.
DEFAULT_CONTEXT_WINDOW = 200_000

# The 1M-context beta. build_client_options enables it when the chosen window exceeds the 200k default.
CONTEXT_1M_BETA: SdkBeta = "context-1m-2025-08-07"

# Stable persisted-shape floor. Exact provider/model ceilings are manifest policy enforced only on
# new PUT/PATCH selections, so catalog churn cannot invalidate an existing agent at boot.
_CTX_MIN = 1_000
_CLAUDE_CTX_MAX = 1_000_000

ADAPTIVE_THINKING = ThinkingConfigAdaptive(type="adaptive", display="summarized")


def _resolve_agent_dir() -> pl.Path:
    # Mirrors the agent_dir field, but resolved from env before the config exists so the store path can be located.
    if os.environ.get("AGENT_DIR"):
        return pl.Path(os.environ["AGENT_DIR"]).expanduser().resolve()
    return _DEFAULT_AGENT_DIR


def config_store_path() -> pl.Path:
    """The writable per-agent config store (the nested config, written by PUT /config)."""
    return _resolve_agent_dir() / "data" / "config.json"


def codex_proxy_auth_path() -> pl.Path:
    """Proxy-owned ChatGPT OAuth file, kept with the agent's persisted private data."""
    return _resolve_agent_dir() / "data" / "claude-code-proxy" / "codex" / "auth.json"


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


def atomic_write_text(path: pl.Path, text: str) -> None:
    """Write text to path atomically and durably: write a uniquely named sibling temp file, fsync it,
    rename over the target, then fsync the directory so a power loss cannot land the rename ahead of
    the data blocks and leave a zeroed file. The unique temp name keeps concurrent writers (coroutines
    dispatch these writes to worker threads) last-write-wins instead of torn. The single owner of the
    tmp-write + os.replace recipe (config.json here, state.json in state_store)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        pl.Path(tmp_name).replace(path)
    finally:
        pl.Path(tmp_name).unlink(missing_ok=True)  # no-op after a successful replace; removes the orphan on failure
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _write_config_store(data: dict[str, pyd.JsonValue]) -> None:
    atomic_write_text(config_store_path(), json.dumps(data, indent=2))


@contextlib.contextmanager
def config_write_lock() -> tp.Iterator[None]:
    """Serialize config read-modify-write transactions across API worker threads."""
    with _CONFIG_WRITE_LOCK:
        yield


def update_config_store(updates: dict[str, pyd.JsonValue]) -> None:
    """Merge top-level updates into the store (atomic tmp+rename). A None clears the key; non-field
    keys are rejected. `provider` is replaced wholesale by the caller (deep-merge happens before this
    in the PUT handler); other keys are scalar prefs."""
    fields = VestaConfig.model_fields
    for key in updates:
        if key not in fields:
            raise ValueError(f"{key!r} is not a config field")
    with config_write_lock():
        current = read_config_store()
        for key, value in updates.items():
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value
        _write_config_store(current)


def load_notification_rules() -> list[NotificationInterruptRule]:
    """The current ruleset, read live from the store on disk (not the boot-time config) via
    read_config_store, so monitor_loop and edits stay in step without a restart. It runs on the
    per-tick notification hot path, so a transient unreadable store (OSError) yields no rules rather
    than raising; one malformed rule (e.g. an invalid regex from a newer skill) is dropped and the
    rest kept."""
    try:
        store = read_config_store()
    except OSError as exc:
        logger.error(f"config store unreadable ({exc}); ignoring it")
        return []
    section = store["notification_rules"] if "notification_rules" in store else []
    if not isinstance(section, list):
        logger.error("config store notification_rules is not a list; ignoring")
        return []
    rules: list[NotificationInterruptRule] = []
    for item in section:
        try:
            rules.append(NotificationInterruptRule.model_validate(item))
        except pyd.ValidationError as exc:
            logger.error(f"dropping invalid notification rule {item} — keeping the rest ({exc})")
    return drop_expired(rules, dt.datetime.now(dt.UTC))


def load_active_skills(config: "VestaConfig") -> list[str]:
    """The current active skill list, read live from the store so CLI edits and PUT /config
    are visible to GET /config before the next restart."""
    try:
        store = read_config_store()
    except OSError as exc:
        logger.error(f"config store unreadable ({exc}); using boot-time active_skills")
        return config.active_skills
    if "active_skills" not in store:
        return config.active_skills
    try:
        return VestaConfig.model_validate({"active_skills": store["active_skills"]}).active_skills
    except pyd.ValidationError as exc:
        logger.error(f"config store active_skills is invalid; using boot-time active_skills ({exc})")
        return config.active_skills


class ClaudeOAuth(pyd.BaseModel):
    """Mirrors the `claudeAiOauth` blob in the SDK credentials file (aliases carry the on-disk
    camelCase). Tolerates extra keys: the `claude` CLI owns the file and adds fields we don't model.
    Loaded at boot, never persisted to the store."""

    model_config = pyd.ConfigDict(extra="allow", populate_by_name=True, serialize_by_alias=True)

    access_token: str | None = pyd.Field(default=None, alias="accessToken")
    refresh_token: str | None = pyd.Field(default=None, alias="refreshToken")
    expires_at: int | None = pyd.Field(default=None, alias="expiresAt")
    # The plan tier ("free" | "pro" | "max"); drives the context-window presets the picker offers,
    # since the 1M-context beta is a Max-only entitlement.
    subscription_type: str | None = pyd.Field(default=None, alias="subscriptionType")


def read_claude_oauth() -> "ClaudeOAuth | None":
    """The `claudeAiOauth` blob from the SDK credentials file, or None when absent/unreadable. The
    file is the source of truth (the CLI refreshes it in place); we load it into the model at boot but
    never write it back through the config store."""
    if not CREDENTIALS_PATH.is_file():
        return None
    try:
        data = json.loads(CREDENTIALS_PATH.read_text())
        if isinstance(data, dict) and "claudeAiOauth" in data and isinstance(data["claudeAiOauth"], dict):
            return ClaudeOAuth.model_validate(data["claudeAiOauth"])
    except (json.JSONDecodeError, OSError, pyd.ValidationError) as exc:
        logger.error(f"credentials file {CREDENTIALS_PATH} unreadable ({exc}); ignoring it")
        return None
    return None


# The provider config is a discriminated union by `kind` — it carries the shape invariants (key-backed
# providers require a key; Claude carries thinking + its OAuth blob), while the catalog of model/context
# options lives in the manifest. OpenRouter is free-form because its model catalog is fetched live;
# fixed providers validate against the manifest.
class _KeyBackedConfig(pyd.BaseModel):
    key: pyd.SecretStr

    @pyd.field_validator("key")
    @classmethod
    def _key_is_not_blank(cls, value: pyd.SecretStr) -> pyd.SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("provider key must not be blank")
        return value


class ClaudeConfig(pyd.BaseModel):
    kind: tp.Literal["claude"] = "claude"
    model: _ProviderModel = _DEFAULT_CLAUDE_MODEL
    max_context_tokens: int | None = pyd.Field(default=None, ge=_CTX_MIN, le=_CLAUDE_CTX_MAX)
    thinking: ThinkingConfigAdaptive | ThinkingConfigEnabled | ThinkingConfigDisabled = ADAPTIVE_THINKING
    # Loaded from CREDENTIALS_PATH on the boot path only (load_config; provider.py reads the file
    # itself when deriving status); never persisted, and never read during config validation.
    oauth: ClaudeOAuth | None = None

    @pyd.field_validator("thinking", mode="before")
    @classmethod
    def _parse_thinking(cls, value: object) -> object:
        return _coerce_thinking(value)


class OpenRouterConfig(_KeyBackedConfig):
    kind: tp.Literal["openrouter"] = "openrouter"
    model: _ProviderModel
    # OpenRouter exposes the selected model's real window from /models. There is deliberately no
    # provider-wide upper bound here: the runtime resolves that model-specific ceiling and treats
    # this field only as an optional user cap.
    max_context_tokens: int | None = pyd.Field(default=None, ge=_CTX_MIN)
    # SecretStr redacts it in GET /config; client.py injects the real value into the SDK env. Required:
    # an openrouter provider structurally cannot exist without a key. No thinking field (forced disabled).


class ZaiConfig(_KeyBackedConfig):
    """A Z.AI Coding Plan key used through its Claude Code-compatible endpoint."""

    kind: tp.Literal["zai"] = "zai"
    model: _ProviderModel
    max_context_tokens: int | None = pyd.Field(default=None, ge=_CTX_MIN)


class KimiConfig(_KeyBackedConfig):
    """A Kimi Code membership key used through its Claude Code-compatible endpoint."""

    kind: tp.Literal["kimi"] = "kimi"
    model: _ProviderModel
    max_context_tokens: int | None = pyd.Field(default=None, ge=_CTX_MIN)


class OpenAIConfig(pyd.BaseModel):
    """A ChatGPT subscription used through the local Anthropic-compatible bridge."""

    kind: tp.Literal["openai"] = "openai"
    model: _ProviderModel
    max_context_tokens: int | None = pyd.Field(default=None, ge=_CTX_MIN)


Provider = tp.Annotated[ClaudeConfig | OpenRouterConfig | ZaiConfig | KimiConfig | OpenAIConfig, pyd.Field(discriminator="kind")]


def validate_provider_selection(provider: Provider) -> None:
    """Strictly validate a new fixed-catalog selection without invalidating persisted history.

    Provider catalogs change faster than agent config. VestaConfig therefore validates the stable
    on-disk shape only; PUT/PATCH calls this boundary check before accepting a new selection.
    """
    if not isinstance(provider, OpenRouterConfig):
        _validate_catalog_provider(provider.kind, provider.model, provider.max_context_tokens)


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
    # Ordered interrupt ruleset (first match wins; no match -> interrupt). Edited live via PUT /config
    # and the notifications skill; monitor_loop reads it from the store each tick (see load_notification_rules).
    notification_rules: list[NotificationInterruptRule] = pyd.Field(default_factory=list)
    # When True, a reply containing an em dash, en dash, or ' - ' separator triggers a resend-without-them
    # correction turn (see client.process_message). Off lets the model use dashes freely.
    block_dashes: bool = True
    # Optional skills linked into Claude Code at boot. The entrypoint unions shipped defaults from
    # core/default-skills.txt into this list before core.main starts.
    active_skills: list[str] = pyd.Field(default_factory=list)

    ephemeral: bool = False
    log_level: tp.Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    monitor_tick_interval: int = pyd.Field(default=2, ge=1)
    proactive_check_interval: int = pyd.Field(default=60, ge=1)
    notif_snooze_idle_grace_seconds: float = pyd.Field(default=30.0, gt=0)
    query_timeout: int = pyd.Field(default=120, ge=1)
    response_timeout: int = pyd.Field(default=600, ge=1)
    nightly_memory_hour: int | None = pyd.Field(default=3, ge=0, le=23)
    interrupt_timeout: float = pyd.Field(default=5.0, gt=0)
    ws_port: int = 0
    # SecretStr so it's redacted in GET /config dumps; the auth middleware reads its real value.
    agent_token: pyd.SecretStr | None = None
    agent_dir: pl.Path = pyd.Field(default=_DEFAULT_AGENT_DIR)
    agent_name: str = "vesta"
    # IANA timezone, owned here (not env): clients deliver it via PUT /config and main.py applies it
    # to the process once at boot (tzset). The TZ alias lets a legacy agent seed the field.
    timezone: str = pyd.Field(default="UTC", validation_alias=pyd.AliasChoices("timezone", "TZ"))
    # One-shot freeform setup notes; materialized to data/seed-context.md on boot, read once at first wake.
    seed_context: str = pyd.Field(default="")

    @pyd.field_validator("active_skills", mode="before")
    @classmethod
    def _normalize_active_skills(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("active_skills must be a list of skill names")
        names: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                raise ValueError("active_skills entries must be strings")
            name = item.strip()
            if not name:
                raise ValueError("active_skills entries must not be blank")
            if _SKILL_NAME_RE.fullmatch(name) is None:
                raise ValueError(f"invalid skill name: {name!r}")
            names.add(name)
        return sorted(names)

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
    def notif_trash_dir(self) -> pl.Path:
        # Trashed notifications are moved here rather than deleted, so a too-aggressive trash rule stays
        # recoverable/auditable. A subdir of notifications_dir is safe: the loader globs "*.json"
        # non-recursively and the watcher is recursive=False, so files parked here are never re-scanned.
        return self.notifications_dir / "trash"

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
    validate_provider_catalog = False
    for key, value in data.items():
        if key == "provider" and isinstance(value, dict):
            current_kind = config.provider.kind if config.provider is not None else None
            validate_provider_catalog = (
                "model" in value or "max_context_tokens" in value or (isinstance(value.get("kind"), str) and value["kind"] != current_kind)
            )
            merged = merge_provider(config, tp.cast("dict[str, pyd.JsonValue]", value))
            candidate["provider"] = merged
            updates["provider"] = merged
        else:
            candidate[key] = value
            updates[key] = value
    validated = VestaConfig.model_validate(copy.deepcopy(candidate))
    if validate_provider_catalog and validated.provider is not None:
        validate_provider_selection(validated.provider)
    # Persist notification_rules in canonical, id-stamped form: validate through the model, assign an id
    # to any rule the caller left id-less (so remove-by-id has a stable handle), and store that.
    if "notification_rules" in updates:
        for rule in validated.notification_rules:
            if not rule.id:
                rule.id = uuid.uuid4().hex
        updates["notification_rules"] = [rule.model_dump(mode="json") for rule in validated.notification_rules]
    if "active_skills" in updates:
        updates["active_skills"] = validated.active_skills
    return updates


def _hydrate_claude_oauth(config: VestaConfig) -> VestaConfig:
    """The store never persists the Claude OAuth blob (the SDK CLI owns/refreshes that file), so a
    claude provider arrives with oauth=None; boot loads it from disk here. Only load_config hydrates:
    validating a config (PUT /config, PATCH /provider) is inert and never touches disk."""
    if isinstance(config.provider, ClaudeConfig) and config.provider.oauth is None:
        config.provider = config.provider.model_copy(update={"oauth": read_claude_oauth()})
    return config


def load_config() -> tuple[VestaConfig, list[str]]:
    """Build VestaConfig without ever raising.

    Config is on the container's boot path: an exception here exits the process non-zero, which the
    `on-failure` restart policy retries a few times before giving up and leaving the agent down. So
    drop each offending env override and rebuild, reverting only that field; if nothing is droppable,
    fall back to a default claude provider.
    """
    issues: list[str] = []
    dropped: set[str] = set()
    while True:
        try:
            return _hydrate_claude_oauth(VestaConfig()), issues
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
                token = os.environ["AGENT_TOKEN"] if os.environ.get("AGENT_TOKEN") else None
                return (
                    VestaConfig.model_construct(
                        provider=ClaudeConfig(oauth=read_claude_oauth()),
                        agent_token=pyd.SecretStr(token) if token is not None else None,
                    ),
                    issues,
                )
