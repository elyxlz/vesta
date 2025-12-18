"""MCP registry and building functions."""

from __future__ import annotations

import shlex
import typing as tp
from dataclasses import dataclass

from vesta.config import VestaConfig


class McpServer(tp.TypedDict):
    command: str
    args: tp.NotRequired[list[str]]
    env: tp.NotRequired[dict[str, str]]


McpName = tp.Literal["whatsapp", "reminder", "task", "playwright", "microsoft"]


@dataclass(frozen=True)
class McpDefinition:
    name: str
    tool_suffixes: tuple[str, ...]

    @property
    def tool_ids(self) -> list[str]:
        return [f"mcp__{self.name}__{s}" for s in self.tool_suffixes]


# MCP Server Builders
def _build_uv_mcp(
    config: VestaConfig,
    name: str,
    *,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
    notifications: bool = False,
) -> McpServer:
    mcps_root = config.install_root / "mcps"
    args = [
        "run",
        "--directory",
        str(mcps_root / f"{name}-mcp"),
        f"{name}-mcp",
        "--data-dir",
        str(config.data_dir / f"{name}-mcp"),
        "--log-dir",
        str(config.logs_dir / f"{name}-mcp"),
    ]
    if notifications:
        args.extend(["--notifications-dir", str(config.notifications_dir)])
    if extra_args:
        args.extend(extra_args)

    env = {"MAX_MCP_OUTPUT_TOKENS": str(config.max_mcp_output_tokens)}
    if extra_env:
        env.update(extra_env)

    return {"command": "uv", "args": args, "env": env}


def _build_whatsapp_mcp(config: VestaConfig) -> McpServer:
    build_dir = shlex.quote(str(config.whatsapp_build_dir))
    data_dir = shlex.quote(str(config.data_dir / "whatsapp-mcp"))
    log_dir = shlex.quote(str(config.logs_dir / "whatsapp-mcp"))
    notif_dir = shlex.quote(str(config.notifications_dir))
    return {
        "command": "sh",
        "args": [
            "-c",
            f"cd {build_dir} && go build -o whatsapp-mcp . && "
            f"./whatsapp-mcp --data-dir {data_dir} --log-dir {log_dir} --notifications-dir {notif_dir}",
        ],
        "env": {"MAX_MCP_OUTPUT_TOKENS": str(config.max_mcp_output_tokens)},
    }


def _build_playwright_mcp(config: VestaConfig) -> McpServer:
    mcps_root = config.install_root / "mcps"
    playwright_dir = shlex.quote(str(mcps_root / "playwright-mcp"))
    output_dir = shlex.quote(str(config.playwright_screenshots_dir))
    log_dir = shlex.quote(str(config.logs_dir / "playwright-mcp"))
    return {
        "command": "sh",
        "args": [
            "-c",
            f"cd {playwright_dir} && npm install --silent && "
            f"npx mcp-server-playwright --browser chromium "
            f"--blocked-origins 'googleads.g.doubleclick.net;googlesyndication.com' "
            f"--output-dir {output_dir} --image-responses omit --log-dir {log_dir}",
        ],
        "env": {"MAX_MCP_OUTPUT_TOKENS": str(config.max_mcp_output_tokens)},
    }


MCP_BUILDERS: dict[McpName, tp.Callable[[VestaConfig], McpServer]] = {
    "whatsapp": _build_whatsapp_mcp,
    "reminder": lambda c: _build_uv_mcp(c, "reminder", notifications=True),
    "task": lambda c: _build_uv_mcp(c, "task", notifications=True),
    "playwright": _build_playwright_mcp,
    "microsoft": lambda c: _build_uv_mcp(
        c,
        "microsoft",
        notifications=True,
        extra_env={
            "MICROSOFT_MCP_CLIENT_ID": c.microsoft_mcp_client_id.get_secret_value(),
            "MICROSOFT_MCP_TENANT_ID": c.microsoft_mcp_tenant_id,
        },
    ),
}


def build_mcp_servers(config: VestaConfig) -> dict[str, McpServer]:
    """Build MCP server configs for enabled MCPs."""
    return {name: MCP_BUILDERS[tp.cast(McpName, name)](config) for name in config.mcps}
