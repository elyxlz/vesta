"""MCP tool server exposed to the Claude SDK: restart and completion-mark tools."""

import datetime as dt
import typing as tp

from claude_agent_sdk import create_sdk_mcp_server, tool

from . import logger
from . import models as vm
from . import state_store
from . import vestad_client
from .api import start_ws_server


def _vesta_tools(state: vm.State, config: vm.VestaConfig) -> list[tp.Any]:
    async def _lifecycle_via_vestad(verb: str, request: tp.Callable[[], tp.Awaitable[bool]]) -> dict[str, tp.Any]:
        # vestad owns the container lifecycle: ask it to act (graceful docker restart/stop). It
        # SIGTERMs this process, the agent shuts down cleanly, and vestad restarts it or keeps it
        # stopped. We never exit ourselves — under the on-failure policy a clean self-exit stays down.
        if state.graceful_shutdown.is_set():
            return {"content": [{"type": "text", "text": "Already shutting down."}]}
        logger.shutdown(f"Container {verb} requested via vestad")
        if not await request():
            return {"content": [{"type": "text", "text": f"Could not reach vestad to {verb} — is the daemon running?"}]}
        return {"content": [{"type": "text", "text": f"Container {verb} initiated."}]}

    @tool("restart_vesta", "Restart the agent container. Triggers a full Docker container restart to reload everything.", {})
    async def restart_vesta(args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        return await _lifecycle_via_vestad("restart", vestad_client.request_restart)

    @tool(
        "stop_vesta",
        "Stop the agent container and keep it stopped. vestad records this as user-requested, so the agent stays down across reboots until it's explicitly started again. Use restart_vesta if you just want to reload.",
        {},
    )
    async def stop_vesta(args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        return await _lifecycle_via_vestad("stop", vestad_client.request_stop)

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
        "Call as the final step of the nightly dream, once the dream summary has been written and MEMORY.md has been updated. Records today's run, then (once this turn ends) compacts the conversation and restarts the agent, which resumes the compacted session — so you come back with a clean but continuous context rather than a blank slate.",
        {},
    )
    async def mark_dreamer_complete(args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        state.persisted.last_dreamer_run = dt.datetime.now()
        state.persisted.show_dreamer_summary = True
        state.persisted.last_restart_reason = vm.NIGHTLY_RESTART
        state_store.save_state(state.persisted, config)
        # /compact only works while the session is idle, so we can't compact from inside this
        # mid-turn tool call. Flag it; the message processor compacts at the next idle point and
        # then triggers the restart. The session_id is intentionally kept so the restart resumes
        # the compacted conversation instead of starting fresh.
        state.compact_then_restart = True
        logger.dreamer("Dreamer marked complete by agent — will compact then restart with continuous context")
        return {"content": [{"type": "text", "text": "dreamer marked complete; compacting context then restart"}]}

    return [restart_vesta, stop_vesta, mark_setup_done, mark_migration_applied, mark_dreamer_complete]


def build_vesta_tools_server(state: vm.State, config: vm.VestaConfig) -> tp.Any:
    return create_sdk_mcp_server("vesta-tools", tools=_vesta_tools(state, config))
