import json
import os
import pathlib as pl
import typing as tp

import pydantic as pyd
import pydantic_settings as pyd_settings
from core.cc_sdk.types import ThinkingConfigAdaptive, ThinkingConfigDisabled, ThinkingConfigEnabled


_DEFAULT_AGENT_DIR = pl.Path.home() / "agent"
_THINKING_ENABLED_BUDGET_TOKENS = 10000

# Single source of truth for new-agent defaults, shipped with the agent. vestad reads this same
# file from the embedded agent source to serve GET /agent-defaults, so the default model/provider/
# personality live in exactly one place across the whole system (no Rust/Python duplication).
CONFIG_DEFAULTS_PATH = pl.Path(__file__).parent / "defaults.json"


def _resolve_agent_dir() -> pl.Path:
    """Agent dir resolved straight from the env, mirroring the agent_dir field. Needed before
    the config is built so the writable settings store path can be located."""
    if "AGENT_DIR" in os.environ and os.environ["AGENT_DIR"]:
        return pl.Path(os.environ["AGENT_DIR"]).expanduser().resolve()
    return _DEFAULT_AGENT_DIR


def config_store_path() -> pl.Path:
    """Writable per-agent settings store (sparse overrides), written only by PUT /config.
    Holds the live, user-editable preferences (model, context window, personality, thinking)."""
    return _resolve_agent_dir() / "data" / "config.json"


def _shipped_defaults() -> dict[str, tp.Any]:
    return json.loads(CONFIG_DEFAULTS_PATH.read_text())

# claude-code's assumed window without the 1M beta, and the OpenRouter cap fallback
# when the user hasn't explicitly chosen a context window.
DEFAULT_CONTEXT_WINDOW = 200_000

# The 1M-context beta and the window it unlocks. These are Anthropic-API facts the agent
# owns: build_client_options decides whether to enable the beta and passes both windows to
# cc_sdk for usage reporting, so the transport keeps no model-specific constants of its own.
CONTEXT_1M_BETA = "context-1m-2025-08-07"
EXPANDED_CONTEXT_WINDOW = 1_000_000


class VestaConfig(pyd_settings.BaseSettings):
    """Vesta agent configuration.

    Every field can be overridden via env var (uppercased field name, no prefix).
    Set in ~/.bashrc and run restart_vesta to apply.

    Key overrides:
        AGENT_MODEL   - model name, e.g. "sonnet", "opus", "haiku" (required from env; vestad
                        seeds the default and the provider file overrides it)
        AGENT_NAME    - agent name (default: "vesta")
        AGENT_PROVIDER - "claude" (OAuth) or "openrouter" (API key) (required from env, as AGENT_MODEL)
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
    agent_token: str | None = None

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
    def core_skills_dir(self) -> pl.Path:
        return self.agent_dir / "core" / "skills"

    def skill_dirs(self) -> list[pl.Path]:
        """Return every existing skills/<name>/ directory with a SKILL.md."""
        dirs: list[pl.Path] = []
        for sd in [self.core_skills_dir, self.skills_dir]:
            if sd.exists():
                dirs.extend(p for p in sd.iterdir() if p.is_dir() and (p / "SKILL.md").exists())
        return sorted(dirs)

    @property
    def core_prompts_dir(self) -> pl.Path:
        return self.agent_dir / "core" / "prompts"

    @property
    def dreamer_dir(self) -> pl.Path:
        return self.agent_dir / "dreamer"

    agent_name: str = "vesta"
    # model, provider, and personality have no inline default: their values come from the layered
    # sources in settings_customise_sources (the writable config store, then env, then the shipped
    # defaults.json floor). agent_provider is auth-bound and is never written to the config
    # store; it comes from the env (vesta-provider.env, set by /provider) or the shipped default.
    # agent_model and agent_personality are live preferences edited via PUT /config; build_client_options
    # loads the personality preset (SKILL.md + presets/<value>.md) into the system prompt on every boot.
    # init=False: not constructor args, always populated by the settings sources below (the shipped
    # defaults.json floor guarantees a value, so they can never be unset).
    agent_model: str = pyd.Field(init=False)
    agent_provider: tp.Literal["claude", "openrouter"] = pyd.Field(init=False)
    agent_personality: str = pyd.Field(init=False)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[pyd_settings.BaseSettings],
        init_settings: pyd_settings.PydanticBaseSettingsSource,
        env_settings: pyd_settings.PydanticBaseSettingsSource,
        dotenv_settings: pyd_settings.PydanticBaseSettingsSource,
        file_secret_settings: pyd_settings.PydanticBaseSettingsSource,
    ) -> tuple[pyd_settings.PydanticBaseSettingsSource, ...]:
        # Precedence high -> low: explicit init args, the writable config store (PUT /config),
        # the env, then the shipped defaults floor. The config store wins over env so a PUT takes
        # effect on an agent whose env still carries the old value.
        sources: list[pyd_settings.PydanticBaseSettingsSource] = [init_settings]
        store = config_store_path()
        if store.is_file():
            sources.append(pyd_settings.JsonConfigSettingsSource(settings_cls, json_file=store))
        # LEGACY(remove-when: every fleet agent has written a config.json via PUT /config, i.e. the
        # release after this one has rolled out): env_settings carrying agent_model / agent_personality.
        # New agents get these from the config store; only agents whose env predates the store still
        # read them here. Once none do, env stays purely for identity (WS_PORT/AGENT_TOKEN) and the
        # auth-bound agent_provider, and this note can drop the legacy framing.
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
                # No offending env var to drop (a bad value in the config store, or an invalid field
                # default — a bug, not bad env). Fall back rather than crash-loop the boot. Seed the
                # shipped defaults explicitly so model/provider/personality (which have no inline
                # default) are populated; the remaining fields fall back to their field defaults.
                issues.append(f"configuration could not be validated, using all defaults: {exc}")
                return VestaConfig.model_construct(**_shipped_defaults()), issues
