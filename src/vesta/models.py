import datetime as dt
import pathlib as pl
import typing as tp
import asyncio
import dataclasses as dc

import pydantic as pyd
import pydantic_settings as pyd_settings
from pydantic import SecretStr, field_validator
from claude_agent_sdk import ClaudeSDKClient


class McpServer(tp.TypedDict):
    command: str
    args: tp.NotRequired[list[str]]
    env: tp.NotRequired[dict[str, str]]


@dc.dataclass
class State:
    client: ClaudeSDKClient | None = None
    shutdown_event: asyncio.Event | None = None
    shutdown_count: int = 0
    is_processing: bool = False
    sub_agent_context: str | None = None
    session_id: str | None = None
    pending_system_message: str | None = None
    last_memory_consolidation: dt.datetime | None = None
    processing_lock: asyncio.Lock = dc.field(default_factory=asyncio.Lock)
    conversation_history: list[dict[str, str]] = dc.field(default_factory=list)
    conversation_history_lock: asyncio.Lock = dc.field(default_factory=asyncio.Lock)


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
    nightly_memory_completion_message: str = (
        "I just completed the nightly memory consolidation. "
        "Let me know if you'd like a summary of what was updated in your memory."
    )
    interrupt_timeout: float = 5.0
    enable_whatsapp_greeting: bool = True
    whatsapp_greeting_prompt: str = (
        "Check whether the WhatsApp MCP is authenticated by calling the `authenticate_whatsapp` tool. "
        "If it is authenticated, send a short WhatsApp message to the user letting them know Vesta just came online and is ready to help. "
        "If it is not authenticated, log that status and do not attempt to send a message."
    )

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
    def memory_file(self) -> pl.Path:
        return self.state_dir / "MEMORY.md"

    @property
    def memory_template(self) -> pl.Path:
        return self.install_root / "MEMORY.md.tmp"

    @property
    def system_prompt_file(self) -> pl.Path:
        return self.install_root / "SYSTEM_PROMPT.md"

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

    @property
    def mcp_servers(self) -> dict[str, McpServer]:
        base_env = {"MAX_MCP_OUTPUT_TOKENS": str(self.max_mcp_output_tokens)}
        mcps_root = self.install_root / "mcps"
        servers: dict[str, McpServer] = {
            "microsoft": {
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    str(mcps_root / "microsoft-mcp"),
                    "microsoft-mcp",
                    "--data-dir",
                    str(self.data_dir / "microsoft-mcp"),
                    "--log-dir",
                    str(self.logs_dir / "microsoft-mcp"),
                    "--notifications-dir",
                    str(self.notifications_dir),
                ],
                "env": {
                    **base_env,
                    "MICROSOFT_MCP_CLIENT_ID": self.microsoft_mcp_client_id.get_secret_value(),
                    "MICROSOFT_MCP_TENANT_ID": self.microsoft_mcp_tenant_id,
                },
            },
            "whatsapp": {
                "command": "sh",
                "args": [
                    "-c",
                    f"cd {self.whatsapp_build_dir} && go build -o whatsapp-mcp . && ./whatsapp-mcp --data-dir {self.data_dir / 'whatsapp-mcp'} --log-dir {self.logs_dir / 'whatsapp-mcp'} --notifications-dir {self.notifications_dir}",
                ],
                "env": base_env,
            },
            "reminder": {
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    str(mcps_root / "reminder-mcp"),
                    "reminder-mcp",
                    "--data-dir",
                    str(self.data_dir / "reminder-mcp"),
                    "--log-dir",
                    str(self.logs_dir / "reminder-mcp"),
                    "--notifications-dir",
                    str(self.notifications_dir),
                ],
                "env": base_env,
            },
            "task": {
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    str(mcps_root / "task-mcp"),
                    "task-mcp",
                    "--data-dir",
                    str(self.data_dir / "task-mcp"),
                    "--log-dir",
                    str(self.logs_dir / "task-mcp"),
                ],
                "env": base_env,
            },
            "playwright": {
                "command": "npx",
                "args": [
                    "--prefix",
                    str(mcps_root / "playwright-mcp"),
                    "mcp-server-playwright",
                    "--browser",
                    "chromium",
                    "--blocked-origins",
                    "googleads.g.doubleclick.net;googlesyndication.com",
                    "--output-dir",
                    str(self.playwright_screenshots_dir),
                    "--image-responses",
                    "omit",
                ],
                "env": base_env,
            },
            "what-day": {
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    str(mcps_root / "what-day-mcp"),
                    "what-day-mcp",
                    "--data-dir",
                    str(self.data_dir / "what-day-mcp"),
                    "--log-dir",
                    str(self.logs_dir / "what-day-mcp"),
                ],
                "env": base_env,
            },
            "pdf-reader": {
                "command": "node",
                "args": [
                    str(mcps_root / "pdf-reader-mcp" / "dist" / "index.js"),
                    "--data-dir",
                    str(self.data_dir / "pdf-reader-mcp"),
                    "--log-dir",
                    str(self.logs_dir / "pdf-reader-mcp"),
                ],
                "env": base_env,
            },
        }
        return servers

    @staticmethod
    def get_secret(value: SecretStr | None) -> str | None:
        return value.get_secret_value() if value else None


class Notification(pyd.BaseModel):
    timestamp: dt.datetime
    source: str
    type: str
    message: str
    sender: str | None = None
    metadata: dict[str, tp.Any] = pyd.Field(default_factory=dict)
    file_path: str | None = pyd.Field(default=None, exclude=True)

    def format_for_display(self) -> str:
        meta_str = ""
        if self.metadata:
            meta_items = [f"{k}={v}" for k, v in self.metadata.items() if v]
            meta_str = f" (metadata: {', '.join(meta_items)})" if meta_items else ""

        from_str = self.sender if self.sender else self.source
        return f"[{self.type} from {from_str}]{meta_str}: {self.message}"
