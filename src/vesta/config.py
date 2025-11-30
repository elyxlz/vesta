"""Vesta configuration - runtime settings only."""

import pathlib as pl

import pydantic as pyd
import pydantic_settings as pyd_settings
from pydantic import SecretStr, field_validator


class VestaSettings(pyd_settings.BaseSettings):
    model_config = pyd_settings.SettingsConfigDict(extra="ignore")

    ephemeral: bool = False
    debug: bool = False
    max_mcp_output_tokens: int = 200000
    notification_check_interval: int = 2
    notification_buffer_delay: int = 3
    proactive_check_interval: int = 60
    proactive_check_message: str = "It's been 60 minutes. Is there anything useful you could do right now?"
    response_timeout: int = 180
    memory_agent_timeout: int = 1200
    shutdown_timeout: int = 310
    task_gather_timeout: int = 2
    enable_nightly_memory: bool = True
    nightly_memory_time: int = 4
    nightly_memory_completion_message: str = "Good morning vesta, your memory consolidation has just completed."
    interrupt_timeout: float = 5.0
    enable_whatsapp_greeting: bool = True
    whatsapp_greeting_prompt: str = (
        "Check whether the WhatsApp MCP is authenticated by calling the `authenticate_whatsapp` tool. "
        "If it is authenticated, send a short WhatsApp message to the user letting them know Vesta just came online and is ready to help. "
        "If it is not authenticated, log that status and do not attempt to send a message."
    )
    notification_suffix: str = "If this is important or requires the user's attention, consider sending them a WhatsApp message."
    max_thinking_tokens: int | None = 10000

    # Microsoft MCP secrets
    microsoft_mcp_client_id: SecretStr = pyd.Field(default=SecretStr(""))
    microsoft_mcp_tenant_id: str = "common"

    # OneDrive configuration
    onedrive_token: SecretStr | None = None
    onedrive_client_id: SecretStr | None = None
    onedrive_client_secret: SecretStr | None = None
    onedrive_drive_id: str | None = None
    onedrive_remote_name: str = "onedrive"
    onedrive_remote_path: str = "/"

    state_dir: pl.Path = pyd.Field(default_factory=lambda: pl.Path.home() / ".vesta")

    @field_validator("state_dir", mode="before")
    @classmethod
    def _normalize_state_dir(cls, value: pl.Path | str | None) -> pl.Path:
        if value is None or value == "":
            return pl.Path.home() / ".vesta"
        return pl.Path(value).expanduser().resolve()

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
    def onedrive_dir(self) -> pl.Path:
        return self.state_dir / "onedrive"

    @property
    def rclone_config_file(self) -> pl.Path:
        return self.data_dir / "rclone.conf"

    def get_mcp_data_dir(self, mcp_name: str) -> pl.Path:
        return self.data_dir / f"{mcp_name}-mcp"

    @property
    def playwright_screenshots_dir(self) -> pl.Path:
        return self.get_mcp_data_dir("playwright") / "screenshots"

    @property
    def whatsapp_build_dir(self) -> pl.Path:
        return self.install_root / "mcps" / "whatsapp-mcp-go"
