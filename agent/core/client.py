import asyncio
import collections
import datetime as dt
import json
import os
import signal
import time
import typing as tp
from collections.abc import Mapping

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    HookContext,
    Message,
    RateLimitEvent,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    tool,
    create_sdk_mcp_server,
)
from claude_agent_sdk.types import (
    HookEvent,
    NotificationHookInput,
    PermissionResultAllow,
    PostToolUseFailureHookInput,
    PreCompactHookInput,
    PreToolUseHookInput,
    PostToolUseHookInput,
    StopHookInput,
    SubagentStartHookInput,
    SubagentStopHookInput,
    HookJSONOutput,
    HookCallback,
    ToolPermissionContext,
)

from . import models as vm
from . import logger
from .helpers import get_memory_path
from .events import SubagentStartEvent, SubagentStopEvent, StreamEvent


def format_crash_detail(
    exc: BaseException, stderr_buffer: collections.deque[str], *, fallback: str = "(no stderr captured)"
) -> tuple[int | None, str]:
    """Extract exit_code and format stderr tail from an SDK exception."""
    try:
        exit_code: int | None = exc.exit_code  # ty: ignore[unresolved-attribute]
    except AttributeError:
        exit_code = None
    stderr_tail = "\n".join(stderr_buffer) if stderr_buffer else fallback
    return exit_code, stderr_tail


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


def _build_query(prompt: str, *, timestamp: dt.datetime) -> str:
    if prompt.startswith("/"):
        return prompt
    timestamp_str = timestamp.strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")
    return f"[Current time: {timestamp_str}]\n{prompt}"


_AGENT_TOOLS = ("Task", "Agent")


def _parse_agent_input(input_data: object) -> tuple[str, str]:
    if isinstance(input_data, dict):
        data = tp.cast(dict[str, tp.Any], input_data)
        agent_type = data["subagent_type"] if "subagent_type" in data else "unknown"
        description = data["description"] if "description" in data else ""
    else:
        agent_type = "unknown"
        description = ""
    return agent_type, description


def _format_tool_call(name: str, *, input_data: object, sub_agent_context: str | None) -> tuple[str, str | None]:
    input_str = json.dumps(input_data) if isinstance(input_data, dict) else str(input_data)

    if name in _AGENT_TOOLS:
        agent_type, description = _parse_agent_input(input_data)
        return f"[TASK] [{agent_type}]: {description or input_str}", agent_type

    prefix = f"[{sub_agent_context}] " if sub_agent_context else ""
    return f"[TOOL] {prefix}{name}: {input_str}", sub_agent_context


def filter_tool_lines(text: str) -> str:
    return "\n".join(s for line in text.split("\n") if (s := line.strip()) and not s.startswith("[TOOL]") and not s.startswith("[TASK]"))


def _parse_sdk_message(msg: Message, *, sub_agent_context: str | None) -> tuple[list[str], list[ThinkingBlock], str | None, str | None, bool]:
    if isinstance(msg, ResultMessage):
        session_id: str | None = None
        try:
            session_id = msg.session_id
        except AttributeError:
            pass
        # Log token usage and cost
        try:
            usage_data = msg.usage or {}
            cost = msg.total_cost_usd
            duration_s = msg.duration_ms / 1000 if msg.duration_ms else None
            parts = []
            if usage_data:
                input_tok = usage_data.get("input_tokens", 0)
                output_tok = usage_data.get("output_tokens", 0)
                cache_read = usage_data.get("cache_read_input_tokens", 0)
                cache_create = usage_data.get("cache_creation_input_tokens", 0)
                parts.append(f"in={input_tok} out={output_tok} cache_read={cache_read} cache_write={cache_create}")
            if cost is not None:
                parts.append(f"cost=${cost:.4f}")
            if duration_s is not None:
                parts.append(f"duration={duration_s:.1f}s")
            if parts:
                logger.usage(" | ".join(parts))
        except (AttributeError, TypeError, KeyError):
            pass
        return ([], [], sub_agent_context, session_id, False)

    if isinstance(msg, RateLimitEvent):
        info = msg.rate_limit_info
        log_fn = logger.debug if info.status == "allowed" else logger.warning
        log_fn(f"Rate limit {info.status} (utilization={info.utilization}, type={info.rate_limit_type})")
        return ([], [], sub_agent_context, None, False)

    if isinstance(msg, SystemMessage):
        if msg.subtype == "init":
            sid = msg.data["session_id"][:16] if isinstance(msg.data, dict) and "session_id" in msg.data else "?"
            logger.debug(f"[init] session_id={sid}")
        else:
            raw = json.dumps(msg.data, default=str)
            logger.system(f"[{msg.subtype}] {raw[:500]}")
        return ([], [], sub_agent_context, None, False)

    if not isinstance(msg, AssistantMessage):
        return ([msg] if isinstance(msg, str) else [], [], sub_agent_context, None, False)

    texts = []
    thinking_blocks = []
    has_tool_use = False
    current_context = sub_agent_context

    for block in msg.content:
        if isinstance(block, TextBlock):
            texts.append(block.text)
        elif isinstance(block, ThinkingBlock):
            thinking_blocks.append(block)
        elif isinstance(block, ToolUseBlock):
            has_tool_use = True
            _, new_context = _format_tool_call(block.name, input_data=block.input, sub_agent_context=current_context)
            if new_context:
                current_context = new_context

    return texts, thinking_blocks, current_context, None, has_tool_use


_TOOL_KEYS: dict[str, str] = {
    "Bash": "command",
    "Skill": "skill",
    "Read": "file_path",
    "Write": "file_path",
    "Edit": "file_path",
    "Glob": "pattern",
    "Grep": "pattern",
}


def _tool_summary(name: str, tool_input: dict[str, tp.Any]) -> str:
    if name in _AGENT_TOOLS:
        agent_type, description = _parse_agent_input(tool_input)
        return f"Task [{agent_type}]: {description}"
    if name in _TOOL_KEYS:
        val = tool_input[_TOOL_KEYS[name]] if _TOOL_KEYS[name] in tool_input else "?"
        return f"{name}: {val}"
    raw = json.dumps(tool_input)
    return f"{name}: {raw}"


def _subagent_hook(state: vm.State, *, verb: str, event_type: str) -> HookCallback:
    async def hook(input_data: SubagentStartHookInput | SubagentStopHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        agent_id = input_data["agent_id"]
        agent_type = input_data["agent_type"]
        logger.subagent(f"{verb} [{agent_type}] id={agent_id}")
        event: StreamEvent
        if event_type == "subagent_start":
            event = SubagentStartEvent(type="subagent_start", agent_id=agent_id, agent_type=agent_type)
        else:
            event = SubagentStopEvent(type="subagent_stop", agent_id=agent_id, agent_type=agent_type)
        state.event_bus.emit(event)
        return tp.cast(HookJSONOutput, {})

    return tp.cast(HookCallback, hook)


def _subagent_prefix(input_data: Mapping[str, object]) -> tuple[str, bool]:
    """Extract sub-agent prefix from hook input. SDK adds agent_id/agent_type for sub-agent calls."""
    if "agent_id" not in input_data:
        return "", False
    agent_type = input_data["agent_type"] if "agent_type" in input_data else None
    prefix = f"[SUB:{agent_type}] " if agent_type else "[SUB] "
    return prefix, True


def _make_hooks(state: vm.State) -> dict[HookEvent, list[HookMatcher]]:
    async def log_tool_start(input_data: PreToolUseHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        name = input_data["tool_name"]
        summary = _tool_summary(name, input_data["tool_input"])
        prefix, is_sub = _subagent_prefix(input_data)
        logger.tool(f"{prefix}{summary}")
        state.event_bus.emit({"type": "tool_start", "tool": name, "input": summary, "subagent": is_sub})
        state.touch_activity(f"tool_start:{name}")
        tool_id = tool_use_id or name
        state.active_tools[tool_id] = vm.ActiveTool(name=name, summary=summary, started_at=time.monotonic(), is_subagent=is_sub)
        return tp.cast(HookJSONOutput, {})

    async def log_tool_finish(input_data: PostToolUseHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        name = input_data["tool_name"]
        prefix, is_sub = _subagent_prefix(input_data)
        tool_id = tool_use_id or name
        elapsed = ""
        active = state.active_tools.pop(tool_id, None)
        if active:
            duration = time.monotonic() - active.started_at
            elapsed = f" ({duration:.1f}s)"
        logger.tool(f"{prefix}done: {name}{elapsed}")
        state.event_bus.emit({"type": "tool_end", "tool": name, "subagent": is_sub})
        state.touch_activity(f"tool_end:{name}")
        return tp.cast(HookJSONOutput, {})

    async def log_tool_failure(input_data: PostToolUseFailureHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        name = input_data["tool_name"]
        error = input_data["error"]
        prefix, _ = _subagent_prefix(input_data)
        logger.warning(f"{prefix}Tool failed: {name}: {error}")
        tool_id = tool_use_id or name
        state.active_tools.pop(tool_id, None)
        state.touch_activity(f"tool_fail:{name}")
        return tp.cast(HookJSONOutput, {})

    async def log_compact(input_data: PreCompactHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        trigger = input_data["trigger"]
        logger.client(f"Context compaction starting (trigger={trigger})")
        return tp.cast(HookJSONOutput, {})

    async def log_notification(input_data: NotificationHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        title = input_data["title"] if "title" in input_data else None
        prefix = f"{title}: " if title else ""
        logger.system(f"[{input_data['notification_type']}] {prefix}{input_data['message']}")
        return tp.cast(HookJSONOutput, {})

    async def log_stop(input_data: StopHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        logger.client("Agent execution stopped")
        return tp.cast(HookJSONOutput, {})

    return {
        "PreToolUse": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_start)])],
        "PostToolUse": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_finish)])],
        "PostToolUseFailure": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_failure)])],
        "SubagentStart": [HookMatcher(hooks=[_subagent_hook(state, verb="started", event_type="subagent_start")])],
        "SubagentStop": [HookMatcher(hooks=[_subagent_hook(state, verb="stopped", event_type="subagent_stop")])],
        "PreCompact": [HookMatcher(hooks=[tp.cast(HookCallback, log_compact)])],
        "Notification": [HookMatcher(hooks=[tp.cast(HookCallback, log_notification)])],
        "Stop": [HookMatcher(hooks=[tp.cast(HookCallback, log_stop)])],
    }


def _format_hang_diagnostics(state: vm.State) -> str:
    parts = [f"idle={state.sdk_idle_seconds():.0f}s", f"last_activity={state.last_sdk_activity_label}"]
    longest = state.longest_running_tool()
    if longest:
        duration = time.monotonic() - longest.started_at
        parts.append(f"longest_tool={longest.name} ({duration:.0f}s, sub={longest.is_subagent})")
    if state.active_tools:
        parts.append(f"active_tools={len(state.active_tools)}")
    stderr_tail = list(state.stderr_buffer)[-5:] if state.stderr_buffer else []
    if stderr_tail:
        parts.append(f"stderr_tail={' | '.join(stderr_tail)}")
    return ", ".join(parts)


async def attempt_interrupt(state: vm.State, *, config: vm.VestaConfig, reason: str) -> bool:
    client = state.client
    if not client:
        return False

    try:
        await asyncio.wait_for(client.interrupt(), timeout=config.interrupt_timeout)
        logger.debug(f"Interrupt sent: {reason}")
        return True
    except TimeoutError:
        diag = _format_hang_diagnostics(state)
        logger.error(f"SDK unresponsive, sending SIGTERM for graceful shutdown | reason={reason} | {diag}")
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(10)
        os._exit(1)
    except (OSError, RuntimeError) as e:
        diag = _format_hang_diagnostics(state)
        logger.error(f"Interrupt failed: {e} | {diag}")
        return False


def persist_session_id(session_id: str, *, state: vm.State, config: vm.VestaConfig) -> None:
    state.session_id = session_id
    config.session_file.parent.mkdir(parents=True, exist_ok=True)
    config.session_file.write_text(session_id)
    logger.debug(f"Captured session_id: {session_id[:16]}...")


_STOP = object()


async def _cancel_task(task: asyncio.Task[tp.Any]) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


_WATCHDOG_THRESHOLDS_S = (60, 120, 300)


def _check_sdk_subprocess_alive(state: vm.State) -> bool | None:
    """Check if the SDK subprocess is still running. Returns None if we can't determine."""
    try:
        transport = state.client._transport  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
        process = transport._process  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
        if process is None:
            return False
        return process.returncode is None
    except (AttributeError, TypeError):
        return None


async def _sdk_watchdog(state: vm.State, *, stop: asyncio.Event) -> None:
    warned_at: set[int] = set()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
            break
        except TimeoutError:
            pass
        idle = state.sdk_idle_seconds()
        for threshold in _WATCHDOG_THRESHOLDS_S:
            if idle >= threshold and threshold not in warned_at:
                warned_at.add(threshold)
                alive = _check_sdk_subprocess_alive(state)
                alive_str = f"process_alive={alive}" if alive is not None else "process_alive=unknown"
                diag = _format_hang_diagnostics(state)
                logger.warning(f"SDK silent for {threshold}s | {alive_str} | {diag}")
        # Reset warnings when activity resumes
        if idle < _WATCHDOG_THRESHOLDS_S[0]:
            warned_at.clear()


async def converse(prompt: str, *, state: vm.State, config: vm.VestaConfig, show_output: bool) -> list[str]:
    assert state.client is not None
    client = state.client

    query = _build_query(prompt, timestamp=dt.datetime.now())
    state.touch_activity("query_start")
    state.active_tools.clear()
    try:
        await asyncio.wait_for(client.query(query), timeout=config.query_timeout)
    except TimeoutError:
        await attempt_interrupt(state, config=config, reason="Query timeout")
        raise
    state.touch_activity("query_sent")

    responses: list[str] = []
    assistant_texts: list[str] = []
    sub_agent_context: str | None = None

    def _emit(t: str) -> None:
        logger.assistant(t)
        state.event_bus.emit({"type": "assistant", "text": t})
        assistant_texts.append(t)

    def _emit_thinking(block: ThinkingBlock) -> None:
        if not block.thinking.strip():
            return
        logger.thinking(block.thinking)
        state.event_bus.emit({"type": "thinking", "text": block.thinking, "signature": block.signature})

    response_iter = client.receive_response().__aiter__()

    interrupt_task: asyncio.Task[tp.Any] | None = None
    if state.interrupt_event and not state.interrupt_event.is_set():
        interrupt_task = asyncio.create_task(state.interrupt_event.wait())

    watchdog_stop = asyncio.Event()
    watchdog_task = asyncio.create_task(_sdk_watchdog(state, stop=watchdog_stop))

    try:
        while True:
            anext_task = asyncio.create_task(anext(response_iter, _STOP))
            waitables: set[asyncio.Task[tp.Any]] = {anext_task}
            if interrupt_task and not interrupt_task.done():
                waitables.add(interrupt_task)

            done, pending = await asyncio.wait(waitables, return_when=asyncio.FIRST_COMPLETED, timeout=config.response_timeout)

            if not done:
                await _cancel_task(anext_task)
                await attempt_interrupt(state, config=config, reason="Response timeout")
                raise TimeoutError

            if interrupt_task and interrupt_task in done:
                await attempt_interrupt(state, config=config, reason="New message interrupt")
                await _cancel_task(anext_task)
                # Cancelling anext_task finalizes response_iter, so drain leftover
                # messages with a fresh iterator to keep the stream clean.
                # Emit any text so it's not lost.
                try:
                    drain = client.receive_response().__aiter__()
                    while (leftover := await asyncio.wait_for(anext(drain, None), timeout=5.0)) is not None:
                        texts, thinking_blocks, _, _, _ = _parse_sdk_message(leftover, sub_agent_context=sub_agent_context)
                        if show_output:
                            for block in thinking_blocks:
                                _emit_thinking(block)
                        text = "\n".join(texts) if texts else None
                        if text and show_output:
                            filtered = filter_tool_lines(text)
                            if filtered:
                                _emit(filtered)
                except (TimeoutError, StopAsyncIteration):
                    pass
                break

            result = anext_task.result()
            if result is _STOP:
                break

            state.touch_activity("sdk_message")
            msg = tp.cast(Message, result)
            texts, thinking_blocks, sub_agent_context, session_id, _ = _parse_sdk_message(msg, sub_agent_context=sub_agent_context)
            if session_id and session_id != state.session_id:
                if state.session_id:
                    logger.warning(f"Session ID changed: {state.session_id[:16]} -> {session_id[:16]} (resume may have failed)")
                persist_session_id(session_id, state=state, config=config)
            if show_output:
                for block in thinking_blocks:
                    _emit_thinking(block)
            text = "\n".join(texts) if texts else None
            if not text:
                continue
            responses.append(text)
            if not show_output:
                continue
            filtered = filter_tool_lines(text)
            if filtered:
                _emit(filtered)
    finally:
        watchdog_stop.set()
        await _cancel_task(watchdog_task)
        if interrupt_task and not interrupt_task.done():
            await _cancel_task(interrupt_task)

    return responses


_EM_DASH = "\u2014"
_EN_DASH = "\u2013"
_DASH_WARNING = (
    "[System: your last response contained an em dash, en dash, or ' - ' used as a separator. "
    "Never use these. Use commas, periods, colons, or restructure the sentence. "
    "Resend your last message without them.]"
)


def _contains_dashes(texts: list[str]) -> bool:
    return any(_EM_DASH in t or _EN_DASH in t or " - " in t for t in texts)


_CONTEXT_USAGE_TIMEOUT_S = 10.0


async def _log_context_usage(state: vm.State) -> None:
    if not state.client:
        return
    try:
        usage = await asyncio.wait_for(state.client.get_context_usage(), timeout=_CONTEXT_USAGE_TIMEOUT_S)
        pct = usage["percentage"]
        total = usage["totalTokens"]
        max_tok = usage["maxTokens"]
        log_fn = logger.warning if pct > 80 else logger.usage
        log_fn(f"Context: {pct:.0f}% ({total:,}/{max_tok:,} tokens)")
    except TimeoutError:
        logger.warning(f"get_context_usage hung for {_CONTEXT_USAGE_TIMEOUT_S}s — skipping")
    except (OSError, RuntimeError, KeyError, TypeError):
        pass


async def process_message(msg: str, *, state: vm.State, config: vm.VestaConfig, is_user: bool) -> tuple[list[str], vm.State]:
    responses = await converse(msg, state=state, config=config, show_output=True)
    if responses and _contains_dashes(responses):
        logger.warning("Em/en dash detected in response, sending correction")
        await converse(_DASH_WARNING, state=state, config=config, show_output=True)
    await _log_context_usage(state)
    return responses, state


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


def _build_vesta_tools_server(state: vm.State, config: vm.VestaConfig) -> tp.Any:
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

    return create_sdk_mcp_server("vesta-tools", tools=[restart_vesta, search_conversation_history])


def _make_stderr_handler(state: vm.State) -> tp.Callable[[str], None]:
    def handler(line: str) -> None:
        logger.sdk(line)
        state.stderr_buffer.append(line)

    return handler


async def _approve_all_tools(tool_name: str, tool_input: dict[str, tp.Any], context: ToolPermissionContext) -> PermissionResultAllow:
    return PermissionResultAllow()


_STREAM_IDLE_TIMEOUT_MS = 300_000  # 5 minutes: abort stalled API streams


def build_client_options(config: vm.VestaConfig, state: vm.State) -> ClaudeAgentOptions:
    memory_path = get_memory_path(config)
    if not memory_path.exists():
        raise FileNotFoundError(f"MEMORY.md not found at {memory_path} — cannot start agent without it")
    system_prompt = memory_path.read_text()

    name = config.agent_name
    system_prompt = f"Your name is {name}.\n\n{system_prompt}"

    # Tell the underlying CLI to abort stalled API streams rather than hanging indefinitely
    os.environ.setdefault("CLAUDE_STREAM_IDLE_TIMEOUT_MS", str(_STREAM_IDLE_TIMEOUT_MS))

    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=config.agent_model,
        betas=["context-1m-2025-08-07"],
        hooks=_make_hooks(state),
        permission_mode="bypassPermissions",
        can_use_tool=_approve_all_tools,
        cwd=config.agent_dir,
        setting_sources=["project"],
        add_dirs=[str(config.agent_dir), os.path.expanduser("~")],
        thinking=config.thinking,
        max_buffer_size=10 * 1024 * 1024,
        stderr=_make_stderr_handler(state),
        mcp_servers={"vesta": _build_vesta_tools_server(state, config)},
        resume=state.session_id,
    )
