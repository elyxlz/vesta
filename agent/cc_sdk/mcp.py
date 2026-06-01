"""In-process tool registry exposed to `claude` as a real MCP stdio server.

`create_sdk_mcp_server` does not start anything by itself; it returns a plain
struct of tool definitions. ClaudeSDKClient registers those tools with the bridge
and points `claude` at the `_mcp_stdio` proxy via --mcp-config. When the model
calls a tool, the proxy round-trips to the bridge, which runs the handler here in
the agent process (so handlers can mutate live State).
"""

import dataclasses as dc
import typing as tp

ToolHandler = tp.Callable[[dict[str, tp.Any]], tp.Awaitable[dict[str, tp.Any]]]


@dc.dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, tp.Any]
    handler: ToolHandler


@dc.dataclass
class McpServer:
    name: str
    tools: list[ToolDef]


def tool(
    name: str, description: str, input_schema: dict[str, tp.Any]
) -> tp.Callable[[ToolHandler], ToolDef]:
    def decorator(handler: ToolHandler) -> ToolDef:
        return ToolDef(name=name, description=description, input_schema=input_schema, handler=handler)

    return decorator


def create_sdk_mcp_server(name: str, *, tools: list[ToolDef]) -> McpServer:
    return McpServer(name=name, tools=tools)
