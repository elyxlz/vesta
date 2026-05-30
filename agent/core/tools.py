"""MCP tool server exposed to the Claude SDK: search, restart, completion-mark tools."""

import datetime as dt
import os
import signal
import typing as tp

from claude_agent_sdk import create_sdk_mcp_server, tool

from . import logger
from . import models as vm
from . import state_store
from .api import start_ws_server

_SEARCH_CONVERSATION_HISTORY_DESCRIPTION = (
    "Search past conversation memory using full-text search (SQLite FTS5). "
    "Searches ALL past conversations across sessions and days, not just the current session. "
    "Use this to recall specific past discussions, decisions, or information no longer in context.\n\n"
    "FTS5 query syntax:\n"
    '- Simple words: "meeting notes" finds messages containing both words\n'
    "- Phrases: '\"exact phrase\"' finds the exact phrase\n"
    '- OR: "cats OR dogs" finds messages with either word\n'
    '- Prefix: "sched*" matches schedule, scheduled, scheduling, etc.\n'
    '- NOT: "meeting NOT cancelled" excludes matches\n\n'
    "Results are ranked by relevance with a recency boost — recent conversations surface higher."
)

_SEARCH_CONVERSATION_HISTORY_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "FTS5 search query"},
        "limit": {"type": "integer", "description": "Max results to return (default 20)", "default": 20},
    },
    "required": ["query"],
}


def _format_search_results(results: list[dict[str, str]], *, max_chars: int = 50000) -> str:
    if not results:
        return "No results found."
    lines = []
    total = 0
    for r in results:
        content = r["content"]
        if len(content) > 2000:
            content = content[:2000] + "..."
        line = f"[{r['timestamp']}] {r['role']}: {content}"
        if total + len(line) > max_chars:
            lines.append(f"... ({len(results) - len(lines)} more results truncated)")
            break
        lines.append(line)
        total += len(line)
    return "\n\n".join(lines)


def build_vesta_tools_server(state: vm.State, config: vm.VestaConfig) -> tp.Any:
    @tool("restart_vesta", "Restart the agent container. Triggers a full Docker container restart to reload everything.", {})
    async def restart_vesta(args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        if state.graceful_shutdown and state.graceful_shutdown.is_set():
            if state.shutdown_event:
                state.shutdown_event.set()
            return {"content": [{"type": "text", "text": "Shutdown complete. Sweet dreams."}]}
        logger.shutdown("Container restart requested")
        os.kill(os.getpid(), signal.SIGTERM)
        return {"content": [{"type": "text", "text": "Container restart initiated."}]}

    @tool("search_conversation_history", _SEARCH_CONVERSATION_HISTORY_DESCRIPTION, _SEARCH_CONVERSATION_HISTORY_SCHEMA)
    async def search_conversation_history(args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        query = str(args["query"])
        limit = int(args["limit"]) if "limit" in args else 20
        try:
            results = state.event_bus.search(query, limit=limit)
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Search error: {e}"}]}
        return {"content": [{"type": "text", "text": _format_search_results(results)}]}

    @tool(
        "mark_setup_done",
        "Call once the silent setup steps are complete and you're ready to start talking to the user. This records first-start completion so it doesn't re-run on every reboot. The WebSocket server is already online from boot.",
        {},
    )
    async def mark_setup_done(args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        state.persisted.first_start_done = True
        state_store.save_state(state.persisted, config)
        if state.ws_runner is None:
            state.ws_runner = await start_ws_server(state.event_bus, config, state)
            logger.init(f"WebSocket server started on port {config.ws_port}")
        logger.startup("setup_done marked by agent — WS online")
        return {"content": [{"type": "text", "text": "setup_done; WS online"}]}

    @tool(
        "mark_migration_applied",
        "Call as the final step of a migration prompt, once the migration has actually been applied. Without this call, the migration re-runs on the next boot.",
        {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    )
    async def mark_migration_applied(args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        name = str(args["name"]).strip()
        if not name:
            return {"content": [{"type": "text", "text": "error: name required"}]}
        if name not in state.persisted.applied_migrations:
            state.persisted.applied_migrations.append(name)
            state_store.save_state(state.persisted, config)
        logger.startup(f"Migration marked applied by agent: {name}")
        return {"content": [{"type": "text", "text": f"applied: {name}"}]}

    @tool(
        "mark_dreamer_complete",
        "Call as the final step of the nightly dream, once the dream summary has been written and MEMORY.md has been updated. Records today's run, queues a session reset on the next restart, and triggers a graceful shutdown so the agent comes back with fresh context.",
        {},
    )
    async def mark_dreamer_complete(args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        state.persisted.last_dreamer_run = dt.datetime.now()
        state.persisted.show_dreamer_summary = True
        state.persisted.session_id = None
        state.persisted.last_restart_reason = vm.NIGHTLY_RESTART
        state_store.save_state(state.persisted, config)
        logger.dreamer("Dreamer marked complete by agent — clearing session and restarting")
        if state.graceful_shutdown is not None:
            state.graceful_shutdown.set()
        return {"content": [{"type": "text", "text": "dreamer marked complete; restart imminent"}]}

    return create_sdk_mcp_server(
        "vesta-tools",
        tools=[restart_vesta, search_conversation_history, mark_setup_done, mark_migration_applied, mark_dreamer_complete],
    )
