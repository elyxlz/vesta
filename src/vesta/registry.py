"""Subagent definitions, MCP registry, and building functions."""

from __future__ import annotations

import typing as tp
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk.types import AgentDefinition as SDKAgentDefinition

if tp.TYPE_CHECKING:
    from .config import VestaSettings


class McpServer(tp.TypedDict):
    command: str
    args: tp.NotRequired[list[str]]
    env: tp.NotRequired[dict[str, str]]


ModelType = tp.Literal["sonnet", "opus", "haiku", "inherit"]
McpName = tp.Literal["playwright", "microsoft", "pdf-reader"]
AllMcpName = tp.Literal["whatsapp", "reminder", "task", "what-day", "playwright", "microsoft", "pdf-reader"]


@dataclass(frozen=True)
class McpDefinition:
    name: McpName
    tool_suffixes: tuple[str, ...]

    @property
    def tool_ids(self) -> list[str]:
        return [f"mcp__{self.name}__{s}" for s in self.tool_suffixes]


# MCP Server Builders
def _build_uv_mcp(
    config: VestaSettings,
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


def _build_whatsapp_mcp(config: VestaSettings) -> McpServer:
    return {
        "command": "sh",
        "args": [
            "-c",
            f"cd {config.whatsapp_build_dir} && go build -o whatsapp-mcp . && "
            f"./whatsapp-mcp --data-dir {config.data_dir / 'whatsapp-mcp'} "
            f"--log-dir {config.logs_dir / 'whatsapp-mcp'} "
            f"--notifications-dir {config.notifications_dir}",
        ],
        "env": {"MAX_MCP_OUTPUT_TOKENS": str(config.max_mcp_output_tokens)},
    }


def _build_playwright_mcp(config: VestaSettings) -> McpServer:
    mcps_root = config.install_root / "mcps"
    return {
        "command": "sh",
        "args": [
            "-c",
            f"cd {mcps_root / 'playwright-mcp'} && npm install --silent && "
            f"npx mcp-server-playwright "
            f"--browser chromium "
            f"--blocked-origins 'googleads.g.doubleclick.net;googlesyndication.com' "
            f"--output-dir {config.playwright_screenshots_dir} "
            f"--image-responses omit "
            f"--log-dir {config.logs_dir / 'playwright-mcp'}",
        ],
        "env": {"MAX_MCP_OUTPUT_TOKENS": str(config.max_mcp_output_tokens)},
    }


def _build_pdf_reader_mcp(config: VestaSettings) -> McpServer:
    mcps_root = config.install_root / "mcps"
    return {
        "command": "node",
        "args": [
            str(mcps_root / "pdf-reader-mcp" / "dist" / "index.js"),
            "--data-dir",
            str(config.data_dir / "pdf-reader-mcp"),
            "--log-dir",
            str(config.logs_dir / "pdf-reader-mcp"),
        ],
        "env": {"MAX_MCP_OUTPUT_TOKENS": str(config.max_mcp_output_tokens)},
    }


MCP_BUILDERS: dict[AllMcpName, tp.Callable[[VestaSettings], McpServer]] = {
    "whatsapp": _build_whatsapp_mcp,
    "reminder": lambda c: _build_uv_mcp(c, "reminder", notifications=True),
    "task": lambda c: _build_uv_mcp(c, "task"),
    "what-day": lambda c: _build_uv_mcp(c, "what-day"),
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
    "pdf-reader": _build_pdf_reader_mcp,
}

CORE_MCPS: set[AllMcpName] = {"whatsapp", "reminder", "task", "what-day"}


def build_mcp_servers(config: VestaSettings) -> dict[str, McpServer]:
    """Build MCP server configs for core MCPs + agent MCPs."""
    enabled = CORE_MCPS | get_agent_mcps()
    return {name: MCP_BUILDERS[name](config) for name in enabled}


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    mcp: McpName
    model: ModelType = "inherit"


PLAYWRIGHT_MCP = McpDefinition(
    name="playwright",
    tool_suffixes=(
        "browser_click",
        "browser_close",
        "browser_console_messages",
        "browser_drag",
        "browser_evaluate",
        "browser_file_upload",
        "browser_fill_form",
        "browser_handle_dialog",
        "browser_hover",
        "browser_navigate",
        "browser_navigate_back",
        "browser_network_requests",
        "browser_press_key",
        "browser_resize",
        "browser_select_option",
        "browser_snapshot",
        "browser_take_screenshot",
        "browser_type",
        "browser_wait_for",
        "browser_tabs",
        "browser_install",
        "browser_mouse_click_xy",
        "browser_mouse_drag_xy",
        "browser_mouse_move_xy",
        "browser_pdf_save",
        "browser_start_tracing",
        "browser_stop_tracing",
    ),
)

MICROSOFT_MCP = McpDefinition(
    name="microsoft",
    tool_suffixes=(
        "list_accounts",
        "authenticate_account",
        "complete_authentication",
        "list_emails",
        "get_email",
        "create_email_draft",
        "send_email",
        "reply_to_email",
        "get_attachment",
        "search_emails",
        "update_email",
        "list_events",
        "get_event",
        "create_event",
        "update_event",
        "delete_event",
        "respond_event",
    ),
)

PDF_READER_MCP = McpDefinition(
    name="pdf-reader",
    tool_suffixes=("read_pdf",),
)

MCP_REGISTRY: dict[McpName, McpDefinition] = {
    "playwright": PLAYWRIGHT_MCP,
    "microsoft": MICROSOFT_MCP,
    "pdf-reader": PDF_READER_MCP,
}

BROWSER_AGENT = AgentDefinition(
    name="browser",
    description="Web browsing, screenshots, site navigation patterns, scraping with Playwright",
    mcp="playwright",
    model="haiku",
)

EMAIL_CALENDAR_AGENT = AgentDefinition(
    name="email_calendar",
    description="Email operations, calendar events, scheduling preferences, contact communication styles",
    mcp="microsoft",
)

REPORT_WRITER_AGENT = AgentDefinition(
    name="report_writer",
    description="Document creation, report writing, formatting preferences, writing styles",
    mcp="pdf-reader",
)

# Active agents (BROWSER_AGENT temporarily disabled)
AGENT_REGISTRY: dict[str, AgentDefinition] = {a.name: a for a in [EMAIL_CALENDAR_AGENT, REPORT_WRITER_AGENT]}


def get_agent_names() -> list[str]:
    return list(AGENT_REGISTRY.keys())


def get_agent_tool_ids(agent_name: str) -> list[str]:
    return MCP_REGISTRY[AGENT_REGISTRY[agent_name].mcp].tool_ids


def get_all_agent_tool_ids() -> list[str]:
    return [t for a in AGENT_REGISTRY.values() for t in MCP_REGISTRY[a.mcp].tool_ids]


def get_agent_mcps() -> set[McpName]:
    return {a.mcp for a in AGENT_REGISTRY.values()}


def load_memory_template(name: str) -> str:
    path = Path(__file__).parent / "templates" / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Memory template not found: {path}")
    return path.read_text()


def get_memory_templates() -> dict[str, str]:
    templates = {"main": load_memory_template("main")}
    templates.update({name: load_memory_template(name) for name in AGENT_REGISTRY})
    return templates


def generate_delegation_prompt() -> str:
    lines = [
        "## Sub-Agent Delegation",
        "",
        "You have specialized sub-agents. **Always delegate to these agents instead of calling their tools directly:**",
        "",
    ]
    for agent in AGENT_REGISTRY.values():
        mcp = MCP_REGISTRY[agent.mcp]
        lines.append(f"- **{agent.name}**: {agent.description}")
        lines.append(f'  - Delegate via: `Task(subagent_type="{agent.name}", ...)`')
        lines.append(f"  - Do NOT call `mcp__{mcp.name}__*` tools directly")
        lines.append("")
    return "\n".join(lines)


def build_all_agents(config: VestaSettings) -> dict[str, SDKAgentDefinition]:
    from .memory import init_all_memories, load_memory

    init_all_memories(config)
    return {
        name: SDKAgentDefinition(
            description=agent.description,
            prompt=load_memory(config, agent_name=name),
            tools=get_agent_tool_ids(name),
            model=agent.model,
        )
        for name, agent in AGENT_REGISTRY.items()
    }
