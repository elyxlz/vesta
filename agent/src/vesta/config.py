import pathlib as pl
import typing as tp

import pydantic as pyd
import pydantic_settings as pyd_settings
from claude_agent_sdk.types import ThinkingConfigAdaptive, ThinkingConfigDisabled, ThinkingConfigEnabled


_DEFAULT_ROOT = pl.Path.home() / "vesta"


class VestaConfig(pyd_settings.BaseSettings):
    """Vesta agent configuration.

    Every field can be overridden via env var (uppercased field name, no prefix).
    Set in ~/.bashrc and run restart_vesta to apply.

    Key overrides:
        AGENT_MODEL   - model name, e.g. "sonnet", "opus", "haiku" (default: "opus")
        AGENT_NAME    - agent name (default: "vesta")
        LOG_LEVEL     - DEBUG | INFO | WARNING | ERROR (default: "INFO")
        THINKING      - adaptive | enabled | disabled (default: "adaptive")
        PROACTIVE_CHECK_INTERVAL - seconds between proactive checks (default: 60)
        NIGHTLY_MEMORY_HOUR      - hour 0-23 for nightly dream, unset to disable (default: 3)
        RESPONSE_TIMEOUT         - max seconds for a single response (default: 600)
    """

    model_config = pyd_settings.SettingsConfigDict(extra="ignore")

    ephemeral: bool = False
    log_level: tp.Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    monitor_tick_interval: int = pyd.Field(default=2, ge=1)
    proactive_check_interval: int = pyd.Field(default=60, ge=1)
    query_timeout: int = pyd.Field(default=120, ge=1)
    response_timeout: int = pyd.Field(default=600, ge=1)
    nightly_memory_hour: int | None = pyd.Field(default=3, ge=0, le=23)
    interrupt_timeout: float = pyd.Field(default=5.0, gt=0)
    thinking: ThinkingConfigAdaptive | ThinkingConfigEnabled | ThinkingConfigDisabled = ThinkingConfigAdaptive(type="adaptive")
    ws_port: int = 0
    agent_token: str | None = None

    root: pl.Path = pyd.Field(default=_DEFAULT_ROOT)

    @pyd.field_validator("root", mode="before")
    @classmethod
    def _normalize_root(cls, value: pl.Path | str | None) -> pl.Path:
        if value is None or value == "":
            return _DEFAULT_ROOT
        return pl.Path(value).expanduser().resolve()

    @property
    def notifications_dir(self) -> pl.Path:
        return self.root / "notifications"

    @property
    def data_dir(self) -> pl.Path:
        return self.root / "data"

    @property
    def logs_dir(self) -> pl.Path:
        return self.root / "logs"

    @property
    def skills_dir(self) -> pl.Path:
        return self.root / "skills"

    def skill_dirs(self) -> list[pl.Path]:
        """Return every existing skills/<name>/ directory with a SKILL.md."""
        sd = self.skills_dir
        if not sd.exists():
            return []
        return sorted(p for p in sd.iterdir() if p.is_dir() and (p / "SKILL.md").exists())

    @property
    def prompts_dir(self) -> pl.Path:
        return self.root / "prompts"

    @property
    def dreamer_dir(self) -> pl.Path:
        return self.root / "dreamer"

    @property
    def session_file(self) -> pl.Path:
        return self.data_dir / "session_id"

    agent_name: str = "vesta"
    agent_model: str = "opus"
