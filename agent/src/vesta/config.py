import pathlib as pl
import typing as tp

import pydantic as pyd
import pydantic_settings as pyd_settings


_DEFAULT_ROOT = pl.Path.home() / "vesta"


class VestaConfig(pyd_settings.BaseSettings):
    model_config = pyd_settings.SettingsConfigDict(extra="ignore")

    ephemeral: bool = False
    log_level: tp.Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    notification_check_interval: int = pyd.Field(default=1, ge=1)
    proactive_check_interval: int = pyd.Field(default=60, ge=1)
    query_timeout: int = pyd.Field(default=120, ge=1)
    response_timeout: int = pyd.Field(default=600, ge=1)
    first_token_timeout: int = pyd.Field(default=30, ge=1)
    nightly_memory_hour: int | None = pyd.Field(default=3, ge=0, le=23)
    interrupt_timeout: float = pyd.Field(default=5.0, gt=0)
    max_thinking_tokens: int | None = 10000
    ws_port: int = 7865

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

    @property
    def prompts_dir(self) -> pl.Path:
        return self.root / "prompts"

    @property
    def history_db(self) -> pl.Path:
        return self.data_dir / "history.db"

    @property
    def dreamer_dir(self) -> pl.Path:
        return self.root / "dreamer"

    @property
    def session_file(self) -> pl.Path:
        return self.data_dir / "session_id"

    agent_name: str = "vesta"
    agent_model: str = "opus"
