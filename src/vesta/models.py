import json
import datetime as dt
import pathlib as pl
import typing as tp
import asyncio
import threading
import dataclasses as dc

import pydantic as pyd
import pydantic_settings as pyd_settings
import claude_code_sdk as ccsdk


SERVICE_ICONS = {
    "playwright": "🌐",
    "whatsapp": "📱",
    "reminder": "⏰",
    "task": "✅",
    "microsoft": "📧",
}


Colors = {
    "dim": "\033[2m",
    "cyan": "\033[96m",
    "magenta": "\033[95m",
    "yellow": "\033[93m",
    "green": "\033[92m",
    "reset": "\033[0m",
}


class McpServer(tp.TypedDict):
    command: str
    args: list[str]


@dc.dataclass
class State:
    client: ccsdk.ClaudeSDKClient | None = None
    conversation_history: list[dict[str, tp.Any]] = dc.field(default_factory=list)
    shutdown_event: asyncio.Event | None = None
    shutdown_lock: threading.Lock = dc.field(default_factory=threading.Lock)
    shutdown_count: int = 0
    is_processing: bool = False
    sub_agent_context: str | None = None
    last_context_pct: float = 0.0
    last_memory_consolidation: dt.datetime | None = None


def _get_default_mcp_servers() -> dict[str, McpServer]:
    root = pl.Path(__file__).parent.parent.parent.absolute()
    return {
        "microsoft": {
            "command": "uv",
            "args": [
                "run",
                "--directory",
                "mcps/microsoft-mcp",
                "microsoft-mcp",
                "--data-dir",
                str(root / "data/microsoft-mcp"),
                "--notifications-dir",
                str(root / "notifications"),
            ],
        },
        "whatsapp": {
            "command": "sh",
            "args": [
                "-c",
                f"cd {root}/mcps/whatsapp-mcp-go && go build -o whatsapp-mcp . && ./whatsapp-mcp --data-dir {root}/data/whatsapp-mcp --notifications-dir {root}/notifications",
            ],
        },
        "reminder": {
            "command": "uv",
            "args": [
                "run",
                "--directory",
                "mcps/reminder-mcp",
                "reminder-mcp",
                "--data-dir",
                str(root / "data/reminder-mcp"),
                "--notifications-dir",
                str(root / "notifications"),
            ],
        },
        "task": {
            "command": "uv",
            "args": [
                "run",
                "--directory",
                "mcps/task-mcp",
                "task-mcp",
                "--data-dir",
                str(root / "data/task-mcp"),
            ],
        },
        "playwright": {
            "command": "npx",
            "args": [
                "--prefix",
                "mcps/playwright-mcp",
                "mcp-server-playwright",
                "--browser",
                "chromium",
                "--blocked-origins",
                "googleads.g.doubleclick.net;googlesyndication.com",
                "--output-dir",
                str(root / "data/playwright-mcp/screenshots"),
                "--image-responses",
                "omit",
            ],
        },
    }


class VestaSettings(pyd_settings.BaseSettings):
    ephemeral: bool = False
    debug: bool = False
    max_mcp_output_tokens: int = 200000
    notification_check_interval: int = 2
    notification_buffer_delay: int = 3
    proactive_check_interval: int = 60
    proactive_check_message: str = "It's been 60 minutes. Is there anything useful you could do right now?"
    whatsapp_bridge_check_interval: int = 30
    response_timeout: int = 180
    memory_agent_timeout: int = 1200
    typing_animation_delay: float = 0.5
    shutdown_timeout: int = 310
    task_gather_timeout: int = 2
    max_context_tokens: int = 150000
    enable_nightly_memory: bool = True
    nightly_memory_time: int = 4
    mcp_servers: dict[str, McpServer] = pyd.Field(default_factory=_get_default_mcp_servers)


class Notification(pyd.BaseModel):
    timestamp: dt.datetime
    source: str
    type: str
    message: str
    sender: str | None = None
    metadata: dict[str, tp.Any] = pyd.Field(default_factory=dict)
    file_path: str | None = pyd.Field(default=None, exclude=True)

    @classmethod
    def from_file(cls, path: pl.Path) -> "Notification":
        try:
            data = json.loads(path.read_text())
            notif = cls(**data)
            notif.file_path = str(path)
            return notif
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {path}: {e}")
        except Exception as e:
            raise ValueError(f"Failed to parse notification from {path}: {e}")

    def format_for_display(self) -> str:
        meta_str = ""
        if self.metadata:
            meta_items = [f"{k}={v}" for k, v in self.metadata.items() if v]
            meta_str = f" (metadata: {', '.join(meta_items)})" if meta_items else ""

        from_str = self.sender if self.sender else self.source
        return f"[{self.type} from {from_str}]{meta_str}: {self.message}"

    def get_display_info(self) -> tuple[str, str, str]:
        display_sender = self.sender or self.source
        icon = SERVICE_ICONS.get(self.source, "🔔")
        display_msg = self.message[:200] + "..." if len(self.message) > 200 else self.message
        return icon, display_sender, display_msg

    def __repr__(self) -> str:
        display_sender = self.sender or self.source
        msg_preview = self.message[:100] + "..." if len(self.message) > 100 else self.message
        return f"<Notification from {display_sender}: {msg_preview}>"
