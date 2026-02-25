import pathlib as pl

import pydantic as pyd
import pydantic_settings as pyd_settings
from pydantic import Field, field_validator


class VestaConfig(pyd_settings.BaseSettings):
    model_config = pyd_settings.SettingsConfigDict(extra="ignore")

    ephemeral: bool = False
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    notification_check_interval: int = Field(default=2, ge=1)
    notification_buffer_delay: int = Field(default=3, ge=0)
    proactive_check_interval: int = Field(default=60, ge=1)
    proactive_check_message: str = "It's been 60 minutes. Is there anything useful you could do right now?"
    response_timeout: int = Field(default=180, ge=1)
    shutdown_timeout: int = Field(default=310, ge=1)
    nightly_memory_hour: int | None = 4
    interrupt_timeout: float = Field(default=5.0, gt=0)
    whatsapp_greeting_prompt: str | None = (  # None/empty = disabled
        "Check whether WhatsApp is authenticated by running `~/whatsapp authenticate`. "
        "If it is authenticated, send a short WhatsApp message to the user letting them know Vesta just came online and is ready to help. "
        "If it is not authenticated, log that status and do not attempt to send a message."
    )
    notification_suffix: str = "If this is important or requires the user's attention, consider sending them a WhatsApp message."
    max_thinking_tokens: int | None = 10000

    state_dir: pl.Path = pyd.Field(default_factory=lambda: pl.Path.home())

    @field_validator("state_dir", mode="before")
    @classmethod
    def _normalize_state_dir(cls, value: pl.Path | str | None) -> pl.Path:
        if value is None or value == "":
            return pl.Path.home()
        return pl.Path(value).expanduser().resolve()

    @field_validator("nightly_memory_hour", mode="after")
    @classmethod
    def _validate_nightly_memory_hour(cls, value: int | None) -> int | None:
        if value is not None and not (0 <= value <= 23):
            raise ValueError("nightly_memory_hour must be between 0 and 23")
        return value

    @property
    def install_root(self) -> pl.Path:
        return pl.Path(__file__).parent.parent.parent.absolute()

    @property
    def root_dir(self) -> pl.Path:
        return self.state_dir

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
    def whatsapp_build_dir(self) -> pl.Path:
        return self.install_root / "clis" / "whatsapp"

    @property
    def memory_dir(self) -> pl.Path:
        return self.state_dir / "memory"

    @property
    def skills_dir(self) -> pl.Path:
        return self.memory_dir / "skills"

