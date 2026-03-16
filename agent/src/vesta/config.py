import pathlib as pl
import typing as tp

import pydantic as pyd
import pydantic_settings as pyd_settings


class VestaConfig(pyd_settings.BaseSettings):
    model_config = pyd_settings.SettingsConfigDict(extra="ignore")

    ephemeral: bool = False
    log_level: tp.Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    notification_check_interval: int = pyd.Field(default=2, ge=1)
    notification_buffer_delay: int = pyd.Field(default=3, ge=0)
    proactive_check_interval: int = pyd.Field(default=60, ge=1)
    query_timeout: int = pyd.Field(default=120, ge=1)
    response_timeout: int = pyd.Field(default=600, ge=1)
    nightly_memory_hour: int | None = pyd.Field(default=4, ge=0, le=23)
    interrupt_timeout: float = pyd.Field(default=5.0, gt=0)
    max_thinking_tokens: int | None = 10000
    ws_port: int = 7865

    state_dir: pl.Path = pyd.Field(default_factory=lambda: pl.Path.home())

    @pyd.field_validator("state_dir", mode="before")
    @classmethod
    def _normalize_state_dir(cls, value: pl.Path | str | None) -> pl.Path:
        if value is None or value == "":
            return pl.Path.home()
        return pl.Path(value).expanduser().resolve()

    @property
    def install_root(self) -> pl.Path:
        return pl.Path(__file__).parent.parent.parent.absolute()

    @property
    def repo_root(self) -> pl.Path:
        return self.install_root.parent

    @property
    def notifications_dir(self) -> pl.Path:
        return self.state_dir / "notifications"

    @property
    def data_dir(self) -> pl.Path:
        return self.state_dir / "data"

    @property
    def logs_dir(self) -> pl.Path:
        return self.state_dir / "logs"

    @property
    def memory_dir(self) -> pl.Path:
        return self.install_root / "memory"

    @property
    def skills_dir(self) -> pl.Path:
        return self.memory_dir / "skills"

    @property
    def prompts_dir(self) -> pl.Path:
        return self.memory_dir / "prompts"

    @property
    def history_db(self) -> pl.Path:
        return self.data_dir / "history.db"

    @property
    def dreamer_dir(self) -> pl.Path:
        return self.memory_dir / "dreamer"

    @property
    def session_file(self) -> pl.Path:
        return self.data_dir / "session_id"

    @property
    def agent_name(self) -> str:
        name_file = self.state_dir / ".vesta-name"
        try:
            name = name_file.read_text().strip()
            if name:
                return name
        except (OSError, UnicodeDecodeError):
            pass
        return "vesta"
