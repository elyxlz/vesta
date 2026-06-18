import os
import pathlib as pl
import typing as tp

import pydantic as pyd
import pydantic_settings as pyd_settings
from core.cc_sdk.types import ThinkingConfigAdaptive, ThinkingConfigDisabled, ThinkingConfigEnabled


_DEFAULT_AGENT_DIR = pl.Path.home() / "agent"
_THINKING_ENABLED_BUDGET_TOKENS = 10000

# claude-code's assumed window without the 1M beta, and the OpenRouter cap fallback
# when the user hasn't explicitly chosen a context window.
DEFAULT_CONTEXT_WINDOW = 200_000


class VestaConfig(pyd_settings.BaseSettings):
    """Vesta agent configuration.

    Every field can be overridden via env var (uppercased field name, no prefix).
    Set in ~/.bashrc and run restart_vesta to apply.

    Key overrides:
        AGENT_MODEL   - model name, e.g. "sonnet", "opus", "haiku" (default: "opus")
        AGENT_NAME    - agent name (default: "vesta")
        AGENT_PROVIDER - "claude" (OAuth) or "openrouter" (API key) (default: "claude")
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
    agent_model: str = "opus"
    agent_provider: tp.Literal["claude", "openrouter"] = "claude"
    # Active personality preset, read on every boot (a live selector, not consumed once at creation).
    # build_client_options loads the shared personality SKILL.md plus presets/<value>.md into
    # the system prompt. Required from the env: vestad always writes AGENT_PERSONALITY, and the
    # legacy AGENT_SEED_PERSONALITY name is still accepted for agents whose env file predates the rename.
    agent_personality: str = pyd.Field(init=False, validation_alias=pyd.AliasChoices("AGENT_PERSONALITY", "AGENT_SEED_PERSONALITY"))


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
                # No offending env var to drop (would mean an invalid field default — a bug, not
                # bad config). Fall back to pure defaults rather than crash-loop the boot.
                issues.append(f"configuration could not be validated, using all defaults: {exc}")
                return VestaConfig.model_construct(), issues
