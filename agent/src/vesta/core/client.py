import asyncio
import datetime as dt
import hashlib
import json
import os
import signal
import time
import typing as tp

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    HookContext,
    Message,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    tool,
    create_sdk_mcp_server,
)
from claude_agent_sdk.types import (
    PreToolUseHookInput,
    PostToolUseHookInput,
    SubagentStartHookInput,
    SubagentStopHookInput,
    HookJSONOutput,
    HookCallback,
)

import vesta.models as vm
from vesta import logger
from vesta.core.history import history_save, history_search, format_results
from vesta.core.init import get_memory_path
from vesta.events import SubagentStartEvent, SubagentStopEvent, StreamEvent


def _build_query(prompt: str, *, timestamp: dt.datetime) -> str:
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


def _parse_sdk_message(
    msg: Message, *, sub_agent_context: str | None, turn_start: float | None = None, model: str | None = None, state: vm.State | None = None
) -> tuple[list[str], str | None, str | None, bool]:
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
            if model:
                parts.append(f"model={model}")
            if usage_data:
                input_tok = usage_data.get("input_tokens", 0)
                output_tok = usage_data.get("output_tokens", 0)
                cache_read = usage_data.get("cache_read_input_tokens", 0)
                cache_create = usage_data.get("cache_creation_input_tokens", 0)
                # Subtract subagent usage to show main-only tokens
                sub_totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
                if state and state.subagent_usage:
                    for su in state.subagent_usage:
                        sub_totals["input"] += su.get("input", 0)
                        sub_totals["output"] += su.get("output", 0)
                        sub_totals["cache_read"] += su.get("cache_read", 0)
                        sub_totals["cache_write"] += su.get("cache_write", 0)
                    input_tok = max(0, input_tok - sub_totals["input"])
                    output_tok = max(0, output_tok - sub_totals["output"])
                    cache_read = max(0, cache_read - sub_totals["cache_read"])
                    cache_create = max(0, cache_create - sub_totals["cache_write"])
                parts.append(f"in={input_tok} out={output_tok} cache_read={cache_read} cache_write={cache_create}")
            if cost is not None:
                cost_label = "cost" if not (state and state.subagent_usage) else "cost (turn total)"
                parts.append(f"{cost_label}=${cost:.4f}")
            if duration_s is not None:
                parts.append(f"duration={duration_s:.1f}s")
            if turn_start is not None:
                wall_s = time.time() - turn_start
                parts.append(f"wall={wall_s:.1f}s")
            if parts:
                logger.usage(" | ".join(parts))
        except (AttributeError, TypeError, KeyError):
            pass
        # Clear subagent accumulator after logging
        if state:
            state.subagent_usage.clear()
        return ([], sub_agent_context, session_id, False)

    if not isinstance(msg, AssistantMessage):
        return ([msg] if isinstance(msg, str) else [], sub_agent_context, None, False)

    texts = []
    has_tool_use = False
    current_context = sub_agent_context

    for block in msg.content:
        if isinstance(block, TextBlock):
            texts.append(block.text)
        elif isinstance(block, ToolUseBlock):
            has_tool_use = True
            _, new_context = _format_tool_call(block.name, input_data=block.input, sub_agent_context=current_context)
            if new_context:
                current_context = new_context

    return texts, current_context, None, has_tool_use


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


def _parse_subagent_transcript(path: str) -> tuple[str, dict[str, int]]:
    """Parse a subagent transcript JSONL to extract model name and aggregate token usage."""
    model_name = "unknown"
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "assistant":
                    continue
                message = entry.get("message") or {}
                if "model" in message:
                    model_name = message["model"]
                usage = message.get("usage")
                if usage:
                    totals["input"] += usage.get("input_tokens", 0)
                    totals["output"] += usage.get("output_tokens", 0)
                    totals["cache_read"] += usage.get("cache_read_input_tokens", 0)
                    totals["cache_write"] += usage.get("cache_creation_input_tokens", 0)
    except (OSError, ValueError) as e:
        logger.warning(f"Could not parse subagent transcript {path}: {e}")
    return model_name, totals


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
            # Parse transcript for per-subagent usage
            transcript_path = input_data.get("agent_transcript_path", "")
            if transcript_path:
                model, totals = _parse_subagent_transcript(transcript_path)
                if any(totals.values()):
                    logger.usage(
                        f"[sub:{agent_type}] model={model} | in={totals['input']} out={totals['output']} cache_read={totals['cache_read']} cache_write={totals['cache_write']}"
                    )
                    state.subagent_usage.append({"agent_type": agent_type, "model": model, **totals})
        state.event_bus.emit(event)
        return tp.cast(HookJSONOutput, {})

    return tp.cast(HookCallback, hook)


def _subagent_prefix(input_data: dict[str, object]) -> tuple[str, bool]:
    """Extract sub-agent prefix from hook input. SDK adds agent_id/agent_type for sub-agent calls."""
    if "agent_id" not in input_data:
        return "", False
    agent_type = input_data["agent_type"] if "agent_type" in input_data else None
    prefix = f"[SUB:{agent_type}] " if agent_type else "[SUB] "
    return prefix, True


_DEDUP_WINDOW = 60.0  # seconds — block identical whatsapp sends within this window
_sent_bash_hashes: dict[str, float] = {}


def _bash_dedup_hash(tool_input: dict[str, tp.Any]) -> str | None:
    """Return a hash if this is a whatsapp send command, else None."""
    cmd = tool_input.get("command", "")
    if not isinstance(cmd, str) or "whatsapp send" not in cmd:
        return None
    return hashlib.md5(cmd.strip().encode()).hexdigest()


def _make_hooks(
    state: vm.State,
) -> tuple[HookCallback, HookCallback, HookCallback, HookCallback]:
    async def log_tool_start(input_data: PreToolUseHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        name = input_data["tool_name"]
        tool_input = input_data["tool_input"]
        summary = _tool_summary(name, tool_input)
        prefix, is_sub = _subagent_prefix(input_data)  # type: ignore[arg-type]

        # Dedup: block identical whatsapp sends within the window
        if name == "Bash":
            h = _bash_dedup_hash(tool_input)
            if h is not None:
                now = time.time()
                # Expire old entries
                expired = [k for k, v in _sent_bash_hashes.items() if now - v > _DEDUP_WINDOW]
                for k in expired:
                    del _sent_bash_hashes[k]
                if h in _sent_bash_hashes:
                    age = now - _sent_bash_hashes[h]
                    logger.warning(f"Duplicate whatsapp send blocked (identical command {age:.0f}s ago)")
                    return tp.cast(
                        HookJSONOutput,
                        {"decision": "block", "reason": f"Duplicate send blocked: identical whatsapp command was already sent {age:.0f}s ago"},
                    )
                _sent_bash_hashes[h] = now

        logger.tool(f"{prefix}{summary}")
        state.event_bus.set_state("tool_use")
        state.event_bus.emit({"type": "tool_start", "tool": name, "input": summary, "subagent": is_sub})
        return tp.cast(HookJSONOutput, {})

    async def log_tool_finish(input_data: PostToolUseHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        name = input_data["tool_name"]
        prefix, is_sub = _subagent_prefix(input_data)  # type: ignore[arg-type]
        logger.tool(f"{prefix}done: {name}")
        state.event_bus.emit({"type": "tool_end", "tool": name, "subagent": is_sub})
        state.event_bus.set_state("thinking")
        return tp.cast(HookJSONOutput, {})

    return (
        tp.cast(HookCallback, log_tool_start),
        tp.cast(HookCallback, log_tool_finish),
        _subagent_hook(state, verb="started", event_type="subagent_start"),
        _subagent_hook(state, verb="stopped", event_type="subagent_stop"),
    )


async def attempt_interrupt(state: vm.State, *, config: vm.VestaConfig, reason: str) -> bool:
    logger.interrupt(f"Starting interrupt attempt: {reason}")

    client = state.client
    if not client:
        logger.interrupt("No client, aborting")
        return False

    try:
        await asyncio.wait_for(client.interrupt(), timeout=config.interrupt_timeout)
        logger.interrupt(f"{reason}: interrupt sent")
        return True
    except TimeoutError:
        logger.error("SDK unresponsive, sending SIGTERM for graceful shutdown")
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(10)
        os._exit(1)
    except (OSError, RuntimeError) as e:
        logger.error(f"Interrupt failed: {e}")
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


async def converse(prompt: str, *, state: vm.State, config: vm.VestaConfig, show_output: bool, turn_start: float | None = None) -> list[str]:
    assert state.client is not None
    client = state.client
    state.subagent_usage.clear()

    query = _build_query(prompt, timestamp=dt.datetime.now())
    try:
        await asyncio.wait_for(client.query(query), timeout=config.query_timeout)
    except TimeoutError:
        await attempt_interrupt(state, config=config, reason="Query timeout")
        raise

    responses: list[str] = []
    assistant_texts: list[str] = []
    sub_agent_context: str | None = None

    def _emit(t: str) -> None:
        logger.assistant(t)
        state.event_bus.emit({"type": "assistant", "text": t})
        assistant_texts.append(t)

    response_iter = client.receive_response().__aiter__()

    interrupt_task: asyncio.Task[tp.Any] | None = None
    if state.interrupt_event and not state.interrupt_event.is_set():
        interrupt_task = asyncio.create_task(state.interrupt_event.wait())

    got_first_token = False
    try:
        while True:
            anext_task = asyncio.create_task(anext(response_iter, _STOP))
            waitables: set[asyncio.Task[tp.Any]] = {anext_task}
            if interrupt_task and not interrupt_task.done():
                waitables.add(interrupt_task)

            timeout = config.response_timeout if got_first_token else config.first_token_timeout
            done, pending = await asyncio.wait(waitables, return_when=asyncio.FIRST_COMPLETED, timeout=timeout)

            if not done:
                await _cancel_task(anext_task)
                reason = "Response timeout" if got_first_token else f"First token timeout ({config.first_token_timeout}s)"
                await attempt_interrupt(state, config=config, reason=reason)
                raise TimeoutError

            if interrupt_task and interrupt_task in done:
                logger.interrupt("Conversation interrupted by new message")
                await attempt_interrupt(state, config=config, reason="New message interrupt")
                await _cancel_task(anext_task)
                # Cancelling anext_task finalizes response_iter, so drain leftover
                # messages with a fresh iterator to keep the stream clean.
                # Emit any text so it's not lost.
                try:
                    drain = client.receive_response().__aiter__()
                    while (leftover := await asyncio.wait_for(anext(drain, None), timeout=5.0)) is not None:
                        texts, _, _, _ = _parse_sdk_message(
                            tp.cast(Message, leftover),
                            sub_agent_context=sub_agent_context,
                            turn_start=turn_start,
                            model=config.agent_model,
                            state=state,
                        )
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

            got_first_token = True
            msg = tp.cast(Message, result)
            texts, sub_agent_context, session_id, _ = _parse_sdk_message(
                msg, sub_agent_context=sub_agent_context, turn_start=turn_start, model=config.agent_model, state=state
            )
            if session_id and session_id != state.session_id:
                persist_session_id(session_id, state=state, config=config)
            text = "\n".join(texts) if texts else None
            if not text:
                continue
            if not show_output:
                responses.append(text)
                continue
            filtered = filter_tool_lines(text)
            if filtered:
                _emit(filtered)
    finally:
        if interrupt_task and not interrupt_task.done():
            await _cancel_task(interrupt_task)

    if state.history is not None:
        combined = "\n".join(r for r in (assistant_texts or responses) if r and r.strip())
        if combined:
            history_save(state.history, "assistant", combined, session_id=state.session_id)

    return responses


async def process_message(msg: str, *, state: vm.State, config: vm.VestaConfig, is_user: bool) -> tuple[list[str], vm.State]:
    turn_start = time.time()
    if state.history is not None:
        role = "user" if is_user else "system"
        history_save(state.history, role, msg, session_id=state.session_id)
    responses = await converse(msg, state=state, config=config, show_output=True, turn_start=turn_start)
    return responses, state


_SEARCH_HISTORY_DESCRIPTION = (
    "Search past conversation memory using full-text search (SQLite FTS5). "
    "Searches ALL past conversations across sessions and days, not just the current session. "
    "Use this to recall specific past discussions, decisions, or information no longer in context.\n\n"
    "FTS5 query syntax:\n"
    '- Simple words: "meeting notes" finds messages containing both words\n'
    "- Phrases: '\"exact phrase\"' finds the exact phrase\n"
    '- OR: "cats OR dogs" finds messages with either word\n'
    '- Prefix: "sched*" matches schedule, scheduled, scheduling, etc.\n'
    '- NOT: "meeting NOT cancelled" excludes matches\n\n'
    "Returns messages in chronological order with timestamps and roles (user/assistant/system)."
)

_SEARCH_HISTORY_SCHEMA = {
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

    @tool("search_history", _SEARCH_HISTORY_DESCRIPTION, _SEARCH_HISTORY_SCHEMA)
    async def search_history(args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        if state.history is None:
            return {"content": [{"type": "text", "text": "History store not available."}]}
        query = str(args["query"])
        limit = int(args["limit"]) if "limit" in args else 20
        try:
            results = history_search(state.history, query, limit=limit)
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Search error: {e}"}]}
        return {"content": [{"type": "text", "text": format_results(results)}]}

    return create_sdk_mcp_server("vesta-tools", tools=[restart_vesta, search_history])


def build_client_options(config: vm.VestaConfig, state: vm.State) -> ClaudeAgentOptions:
    memory_path = get_memory_path(config)
    if not memory_path.exists():
        raise FileNotFoundError(f"MEMORY.md not found at {memory_path} — cannot start agent without it")
    system_prompt = memory_path.read_text()

    name = config.agent_name
    system_prompt = f"Your name is {name}.\n\n{system_prompt}"

    pre_hook, post_hook, subagent_start_hook, subagent_stop_hook = _make_hooks(state)

    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=config.agent_model,
        hooks={
            "PreToolUse": [HookMatcher(hooks=[pre_hook])],
            "PostToolUse": [HookMatcher(hooks=[post_hook])],
            "SubagentStart": [HookMatcher(hooks=[subagent_start_hook])],
            "SubagentStop": [HookMatcher(hooks=[subagent_stop_hook])],
        },
        permission_mode="bypassPermissions",
        cwd=config.root,
        setting_sources=["project"],
        add_dirs=[str(config.root)],
        max_thinking_tokens=config.max_thinking_tokens,
        max_buffer_size=10 * 1024 * 1024,
        stderr=lambda line: logger.sdk(line),
        mcp_servers={"vesta": _build_vesta_tools_server(state, config)},
        resume=state.session_id,
    )
