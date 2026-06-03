"""Unix-socket bridge: the agent-side endpoint for hook events and MCP tool calls.

Both the hook forwarder and the MCP stdio proxy connect here and exchange one
newline-delimited JSON request/reply per turn. Hook payloads are dispatched to the
registered HookMatchers (plus client-internal SessionStart/Stop handlers); MCP
calls run the registered tool handlers in this process so they see live State.
"""

import asyncio
import dataclasses as dc
import json
import typing as tp

from .messages import HookContext, HookMatcher
from .mcp import ToolDef
from .types import HookEvent

InternalHook = tp.Callable[[dict[str, tp.Any]], tp.Awaitable[None]]
LogFn = tp.Callable[[str], None]


@dc.dataclass
class Bridge:
    socket_path: str
    hooks: dict[HookEvent, list[HookMatcher]] = dc.field(default_factory=dict)
    tools: dict[str, ToolDef] = dc.field(default_factory=dict)
    internal: dict[str, list[InternalHook]] = dc.field(default_factory=dict)
    log: LogFn | None = None
    _server: asyncio.AbstractServer | None = None

    def on(self, event: str, handler: InternalHook) -> None:
        self.internal.setdefault(event, []).append(handler)

    def register_tools(self, defs: tp.Iterable[ToolDef]) -> None:
        for d in defs:
            self.tools[d.name] = d

    async def start(self) -> None:
        self._server = await asyncio.start_unix_server(self._handle_conn, path=self.socket_path)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except (OSError, RuntimeError):
                pass
            self._server = None

    async def _handle_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    request = json.loads(line.decode())
                except json.JSONDecodeError:
                    continue
                reply = await self._dispatch(request) if isinstance(request, dict) else {}
                writer.write((json.dumps(reply) + "\n").encode())
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()

    async def _dispatch(self, request: dict[str, tp.Any]) -> dict[str, tp.Any]:
        kind = request["kind"] if "kind" in request else ""
        if kind == "hook":
            event = request["event"] if "event" in request else ""
            payload = request["payload"] if "payload" in request and isinstance(request["payload"], dict) else {}
            await self._run_hooks(event, payload)
            return {"output": {}}
        if kind == "mcp":
            return await self._run_mcp(request)
        return {}

    async def _run_hooks(self, event: str, payload: dict[str, tp.Any]) -> None:
        if event in self.internal:
            for handler in self.internal[event]:
                try:
                    await handler(payload)
                except Exception as exc:  # internal bookkeeping must never break the turn
                    self._warn(f"internal hook {event} failed: {exc}")
        matchers = self.hooks[tp.cast(HookEvent, event)] if event in self.hooks else []
        tool_use_id = payload["tool_use_id"] if "tool_use_id" in payload else None
        for matcher in matchers:
            for callback in matcher.hooks:
                try:
                    await callback(payload, tool_use_id, HookContext())
                except Exception as exc:
                    self._warn(f"hook {event} callback failed: {exc}")

    async def _run_mcp(self, request: dict[str, tp.Any]) -> dict[str, tp.Any]:
        op = request["op"] if "op" in request else ""
        if op == "list":
            return {"tools": [{"name": d.name, "description": d.description, "inputSchema": d.input_schema} for d in self.tools.values()]}
        if op == "call":
            name = request["name"] if "name" in request else ""
            arguments = request["arguments"] if "arguments" in request and isinstance(request["arguments"], dict) else {}
            if name not in self.tools:
                return {"error": f"unknown tool: {name}"}
            try:
                result = await self.tools[name].handler(arguments)
            except Exception as exc:
                self._warn(f"tool {name} failed: {exc}")
                return {"error": str(exc)}
            return result if isinstance(result, dict) else {"content": [{"type": "text", "text": str(result)}]}
        return {"error": f"unknown mcp op: {op}"}

    def _warn(self, message: str) -> None:
        if self.log is not None:
            self.log(message)
