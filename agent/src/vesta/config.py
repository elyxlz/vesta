import json
import pathlib as pl
import typing as tp

import pydantic as pyd
import pydantic_settings as pyd_settings


_DEFAULT_ROOT = pl.Path.home() / "vesta"


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

    # Context nap settings (hot-reloadable via config.json)
    context_nap_soft: int = pyd.Field(default=50, ge=10, le=90)    # % — notify user, nap on inactivity
    context_nap_hard: int = pyd.Field(default=70, ge=20, le=95)    # % — force nap immediately
    context_check_interval: int = pyd.Field(default=900, ge=60)    # seconds — status + nap check cycle
    context_nap_inactivity: int = pyd.Field(default=600, ge=60)   # seconds — inactivity before auto-nap

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

    @property
    def config_file(self) -> pl.Path:
        return self.root / "config.json"

    def reload_from_file(self) -> bool:
        """Re-read config.json and update mutable fields in-place.

        Returns True if any field changed, False otherwise.
        Only updates fields that are present in the JSON file.
        """
        path = self.config_file
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False

        changed = False
        # Only allow hot-reloading these specific fields
        _HOT_RELOAD_FIELDS = {
            "context_nap_soft", "context_nap_hard",
            "context_check_interval", "context_nap_inactivity",
            "nightly_memory_hour", "proactive_check_interval",
            "notification_check_interval", "log_level",
        }
        for key, value in data.items():
            if key in _HOT_RELOAD_FIELDS and hasattr(self, key):
                current = getattr(self, key)
                if current != value:
                    object.__setattr__(self, key, value)
                    changed = True
        return changed
