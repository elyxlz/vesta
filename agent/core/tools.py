"""MCP tool server exposed to the Claude SDK: restart and completion-mark tools."""

import datetime as dt
import typing as tp

from claude_agent_sdk import create_sdk_mcp_server, tool

from . import config as cfg
from . import logger, state_store, vestad_client
from . import models as vm
from .api import start_ws_server
from .helpers import clear_notifications
from .upstream_sync import vesta_version


def _opt_str(value: tp.Any) -> str:
    """Normalize an optional string tool arg: a JSON null (or absent) means empty, never 'None'."""
    return str(value).strip() if value is not None else ""


def _lifecycle_tools(state: vm.State) -> list[tp.Any]:
    async def _lifecycle_via_vestad(verb: str, request: tp.Callable[[], tp.Awaitable[bool]]) -> dict[str, tp.Any]:
        # vestad owns the container lifecycle: ask it to act (graceful docker restart/stop). It
        # SIGTERMs this process, the agent shuts down cleanly, and vestad restarts it or keeps it
        # stopped. We never exit ourselves — under the on-failure policy a clean self-exit stays down.
        if state.graceful_shutdown.is_set():
            return {"content": [{"type": "text", "text": "Already shutting down."}]}
        logger.shutdown(f"Container {verb} requested via vestad")
        # The turn asking for this restart has handled its notification; drop the file now so the
        # SIGTERM doesn't beat the loop's post-turn cleanup and leave it to be re-delivered on reboot.
        clear_notifications(state, state.in_flight_notification_paths)
        state.in_flight_notification_paths = []
        if not await request():
            return {"content": [{"type": "text", "text": f"Could not reach vestad to {verb} — is the daemon running?"}]}
        return {"content": [{"type": "text", "text": f"Container {verb} initiated."}]}

    @tool("restart_vesta", "Restart the agent container. Triggers a full Docker container restart to reload everything.", {})
    async def restart_vesta(_args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        return await _lifecycle_via_vestad("restart", vestad_client.request_restart)

    @tool(
        "stop_vesta",
        "Stop the agent container and keep it stopped. vestad records this as user-requested, so the agent stays down "
        "across reboots until it's explicitly started again. Use restart_vesta if you just want to reload.",
        {},
    )
    async def stop_vesta(_args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        return await _lifecycle_via_vestad("stop", vestad_client.request_stop)

    return [restart_vesta, stop_vesta]


def _mark_tools(state: vm.State, config: cfg.VestaConfig) -> list[tp.Any]:
    @tool(
        "mark_setup_done",
        "Call once the silent setup steps are complete and you're ready to start talking to the user. This records "
        "first-start completion so it doesn't re-run on every reboot. The WebSocket server is already online from boot.",
        {},
    )
    async def mark_setup_done(_args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        state.persisted.first_start_done = True
        await state_store.save_state_async(state.persisted, config)
        if state.ws_runner is None:
            state.ws_runner = await start_ws_server(state.event_bus, config, state)
            logger.init(f"WebSocket server started on port {config.ws_port}")
        logger.startup("setup_done marked by agent — WS online")
        return {"content": [{"type": "text", "text": "setup_done; WS online"}]}

    @tool(
        "mark_migration_applied",
        "Call as the final step of a migration prompt, once the migration has actually been applied. Without this call, "
        "the migration re-runs on the next boot.",
        {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    )
    async def mark_migration_applied(args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        name = str(args["name"]).strip()
        if not name:
            return {"content": [{"type": "text", "text": "error: name required"}]}
        if name not in state.persisted.applied_migrations:
            state.persisted.applied_migrations.append(name)
            await state_store.save_state_async(state.persisted, config)
        logger.startup(f"Migration marked applied by agent: {name}")
        return {"content": [{"type": "text", "text": f"applied: {name}"}]}

    @tool(
        "mark_upstream_synced",
        "Call once the upstream sync completed: the workspace was rebased onto this version's snapshot "
        "(agent-v<version>) and any conflicts are resolved. Records the synced version; without this call "
        "the sync boot turn re-fires on every boot. Call it BEFORE restart_vesta.",
        {},
    )
    async def mark_upstream_synced(_args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        version = vesta_version(config)
        state.persisted.last_synced_version = version
        await state_store.save_state_async(state.persisted, config)
        logger.startup(f"Upstream sync marked complete by agent at v{version}")
        return {"content": [{"type": "text", "text": f"synced: {version}"}]}

    # LEGACY(remove-when: no agent predating the release that ships this rename remains and
    # the 2026-07 workspace migrations are fleet-applied): released migration prompts call
    # the old tool name verbatim.
    @tool("mark_workspace_synced", "Legacy alias of mark_upstream_synced.", {})
    async def mark_workspace_synced(args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        return await mark_upstream_synced.handler(args)

    @tool(
        "mark_dreamer_complete",
        "Call once the nightly dream is fully complete (retrospective done, fixes validated, queue "
        "drained per the dream skill's gate). Records that today's dream ran so it does not re-fire on "
        "the next hourly check. This only records the run; it does not compact or restart. Compact and "
        "restart as your final step via compact_context(followup=..., restart=true).",
        {},
    )
    async def mark_dreamer_complete(_args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        state.persisted.last_dreamer_run = dt.datetime.now()
        await state_store.save_state_async(state.persisted, config)
        logger.dreamer("Dreamer run recorded by agent")
        return {"content": [{"type": "text", "text": "dreamer run recorded"}]}

    return [mark_setup_done, mark_migration_applied, mark_upstream_synced, mark_workspace_synced, mark_dreamer_complete]


def _compaction_tools(state: vm.State) -> list[tp.Any]:
    @tool(
        "compact_context",
        "Compact this conversation at the next idle point (it needs an idle session). `followup` "
        "(optional) is a short instruction to your own next turn after compacting. `restart=true` "
        "(optional) restarts into the compacted session (the nightly dream); omit it for an in-place nap. "
        "`prompt` is how to summarize the conversation; each skill supplies one.",
        {
            "type": "object",
            "properties": {"followup": {"type": "string"}, "restart": {"type": "boolean"}, "prompt": {"type": "string"}},
            "required": ["prompt"],
        },
    )
    async def compact_context(args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        prompt = _opt_str(args["prompt"])
        if not prompt:
            return {"content": [{"type": "text", "text": "error: prompt required"}]}
        # Reject a malformed call where followup/restart leaked in as tool-call tags inside the
        # prompt string; the agent sees this and retries with proper separate arguments.
        if "<parameter name=" in prompt or "</prompt>" in prompt:
            return {"content": [{"type": "text", "text": "error: pass followup and restart as separate arguments, not inside prompt. Retry."}]}
        followup = _opt_str(args["followup"] if "followup" in args else None)
        # Accept only a real True or the string "true": a model emitting "false" must not be coerced truthy.
        raw_restart = args["restart"] if "restart" in args else False
        restart = raw_restart is True or (isinstance(raw_restart, str) and raw_restart.strip().lower() == "true")
        state.pending_compaction = vm.PendingCompaction(prompt=prompt, followup=followup or None, restart=restart)
        logger.client(f"Compaction scheduled by agent (has_followup={bool(followup)}, restart={restart})")
        return {"content": [{"type": "text", "text": "compaction scheduled for end of turn"}]}

    return [compact_context]


def _vesta_tools(state: vm.State, config: cfg.VestaConfig) -> list[tp.Any]:
    return [*_lifecycle_tools(state), *_mark_tools(state, config), *_compaction_tools(state)]


def build_vesta_tools_server(state: vm.State, config: cfg.VestaConfig) -> tp.Any:
    return create_sdk_mcp_server("vesta-tools", tools=_vesta_tools(state, config))
