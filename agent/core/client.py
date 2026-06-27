"""Conversation loop: builds queries, drives the SDK client, handles interrupts and dash-correction."""

import asyncio
import datetime as dt
import os
import typing as tp

import aiohttp

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    Message,
    ResultMessage,
    SystemMessage,
    ThinkingBlock,
)
from claude_agent_sdk.types import PermissionResultAllow, ThinkingConfigDisabled, ToolPermissionContext

from . import logger
from . import models as vm
from . import state_store
from .provider import OPENROUTER_SMALL_FAST_MODEL, TERMINAL_PROVIDER_ERRORS, is_terminal_auth_error, observed_provider_failure
from .config import CONTEXT_1M_BETA, DEFAULT_CONTEXT_WINDOW
from . import diagnostics
from . import sdk_parsing
from .helpers import get_constitution_path, get_memory_path
from .tools import build_vesta_tools_server

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


async def resolve_openrouter_max_tokens(config: vm.VestaConfig) -> int | None:
    """Look up the OpenRouter model's real context window. claude-code assumes a
    200k window for non-Anthropic models (claude-code#46416), so the value passed
    via CLAUDE_CODE_MAX_CONTEXT_TOKENS must reflect what the model actually supports.
    The caller caps this at config.provider.max_context_tokens before passing it to the SDK
    (cache-read cost scales with context size). Returns None on any failure, so
    claude-code falls back to its default, same behavior as before."""
    if not isinstance(config.provider, vm.OpenRouterConfig):
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                OPENROUTER_MODELS_URL,
                headers={"Authorization": f"Bearer {config.provider.key.get_secret_value()}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                body = await resp.json()
    except (TimeoutError, aiohttp.ClientError, ValueError) as e:
        logger.warning(f"OpenRouter context-window lookup failed: {e}")
        return None
    models = body["data"] if isinstance(body, dict) and "data" in body else []
    for entry in models:
        if "id" in entry and entry["id"] == config.provider.model and "context_length" in entry:
            ctx = entry["context_length"]
            if isinstance(ctx, int) and ctx > 0:
                return ctx
    return None


async def attempt_interrupt(state: vm.State, *, config: vm.VestaConfig, reason: str) -> bool:
    client = state.client
    if not client:
        return False

    try:
        await asyncio.wait_for(client.interrupt(), timeout=config.interrupt_timeout)
        logger.debug(f"Interrupt sent: {reason}")
        return True
    except TimeoutError:
        # The SDK didn't ack the interrupt within the window. Log + emit but
        # don't SIGTERM the whole process: in practice this fires more often
        # during heavy thinking or a long-running tool than during a real hang,
        # and the watchdog in core/diagnostics.py SIGTERMs if the SDK is
        # genuinely stuck idle past its higher threshold.
        diag = diagnostics.format_hang_diagnostics(state)
        msg = f"SDK interrupt timed out | reason={reason} | {diag}"
        logger.warning(msg)
        # The event bus has no "warning" severity; like log_context_usage's warning-band
        # crossing (diagnostics.py), surface warn-level conditions as an "error" event.
        state.event_bus.emit({"type": "error", "text": msg})
        return False
    except Exception as e:
        # interrupt() is best-effort. The official SDK surfaces failures across a wide error
        # type (ClaudeSDKError/CLIConnectionError when disconnected, a bare Exception on a
        # control-response error), so catch broadly here and log rather than let an interrupt
        # failure abort the turn the caller is trying to interrupt.
        diag = diagnostics.format_hang_diagnostics(state)
        logger.error(f"Interrupt failed: {e} | {diag}")
        return False


def persist_session_id(session_id: str, *, state: vm.State, config: vm.VestaConfig) -> None:
    state.persisted.session_id = session_id
    state_store.save_state(state.persisted, config)
    logger.debug(f"Captured session_id: {session_id[:16]}...")


_STOP = object()

_INTERRUPT_DRAIN_TIMEOUT_S = 5.0  # cap the post-interrupt drain so a stalled stream can't block forever


async def _cancel_task(task: asyncio.Task[tp.Any]) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def converse(prompt: str, *, state: vm.State, config: vm.VestaConfig, show_output: bool) -> list[str]:
    assert state.client is not None
    client = state.client

    query = sdk_parsing.build_query(prompt, timestamp=dt.datetime.now())
    diagnostics.touch_activity(state, "query_start")
    state.active_tools.clear()
    try:
        await asyncio.wait_for(client.query(query), timeout=config.query_timeout)
    except TimeoutError:
        await attempt_interrupt(state, config=config, reason="Query timeout")
        raise
    diagnostics.touch_activity(state, "query_sent")

    responses: list[str] = []

    def _emit(t: str) -> None:
        logger.assistant(t)
        state.event_bus.emit({"type": "assistant", "text": t})

    def _emit_thinking(block: ThinkingBlock) -> None:
        if not block.thinking.strip():
            return
        logger.thinking(block.thinking)
        state.event_bus.emit({"type": "thinking", "text": block.thinking, "signature": block.signature})

    def _render(texts: list[str], thinking_blocks: list[ThinkingBlock]) -> str | None:
        """Emit thinking + filtered assistant text (when shown); return the joined text so the caller can record it."""
        if show_output:
            for block in thinking_blocks:
                _emit_thinking(block)
        text = "\n".join(texts) if texts else None
        if text and show_output:
            filtered = sdk_parsing.filter_tool_lines(text)
            if filtered:
                _emit(filtered)
        return text

    response_iter = client.receive_response().__aiter__()

    interrupt_task: asyncio.Task[tp.Any] | None = None
    if state.interrupt_event and not state.interrupt_event.is_set():
        interrupt_task = asyncio.create_task(state.interrupt_event.wait())

    watchdog_stop = asyncio.Event()
    watchdog_task = asyncio.create_task(diagnostics.sdk_watchdog(state, stop=watchdog_stop))

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
                    while (leftover := await asyncio.wait_for(anext(drain, None), timeout=_INTERRUPT_DRAIN_TIMEOUT_S)) is not None:
                        texts, thinking_blocks, _ = sdk_parsing.parse_sdk_message(leftover)
                        _render(texts, thinking_blocks)
                except (TimeoutError, StopAsyncIteration):
                    pass
                break

            result = anext_task.result()
            if result is _STOP:
                break

            diagnostics.touch_activity(state, "sdk_message")
            msg = tp.cast(Message, result)
            if isinstance(msg, AssistantMessage):
                state.compacting = False
            texts, thinking_blocks, session_id = sdk_parsing.parse_sdk_message(msg)
            if session_id and session_id != state.persisted.session_id:
                if state.persisted.session_id:
                    logger.warning(f"Session ID changed: {state.persisted.session_id[:16]} -> {session_id[:16]} (resume may have failed)")
                persist_session_id(session_id, state=state, config=config)
            if show_output:
                for block in thinking_blocks:
                    _emit_thinking(block)
            text = "\n".join(texts) if texts else None
            # OpenRouter's upstream 401/402 is caught by its cache proxy. Claude bypasses that proxy,
            # so a terminal auth/billing failure surfaces through the SDK either as the assistant
            # turn's classified error (authentication_failed / billing_error) OR as the result's HTTP
            # status (api_error_status). Check BOTH so a token expiry can't stay invisible to the app.
            auth_lost = (isinstance(msg, AssistantMessage) and is_terminal_auth_error(msg.error)) or (
                isinstance(msg, ResultMessage) and msg.api_error_status in TERMINAL_PROVIDER_ERRORS
            )
            if auth_lost:
                # Flip to not_authenticated, stop the CLI's internal retries, and end the turn cleanly
                # so the app shows "not signed in" in ~3s instead of hanging to the response timeout
                # and restart-looping.
                logger.error("Provider auth lost (terminal upstream 401/402); flipping to not_authenticated")
                state.provider_status = observed_provider_failure(state.provider_status)
                await attempt_interrupt(state, config=config, reason="Provider auth lost")
                break
            if not text:
                continue
            responses.append(text)
            if not show_output:
                continue
            filtered = sdk_parsing.filter_tool_lines(text)
            if filtered:
                _emit(filtered)
    finally:
        state.compacting = False
        watchdog_stop.set()
        await _cancel_task(watchdog_task)
        if interrupt_task and not interrupt_task.done():
            await _cancel_task(interrupt_task)

    return responses


_EM_DASH = "—"
_EN_DASH = "–"
_DASH_WARNING = (
    "[System: your last response contained an em dash, en dash, or ' - ' used as a separator. "
    "Never use these. Use commas, periods, colons, or restructure the sentence. "
    "Resend your last message without them.]"
)


def _contains_dashes(texts: list[str]) -> bool:
    return any(_EM_DASH in t or _EN_DASH in t or " - " in t for t in texts)


async def process_message(msg: str, *, state: vm.State, config: vm.VestaConfig, is_user: bool) -> tuple[list[str], vm.State]:
    responses = await converse(msg, state=state, config=config, show_output=True)
    if responses and _contains_dashes(responses):
        logger.warning("Em/en dash detected in response, sending correction")
        await converse(_DASH_WARNING, state=state, config=config, show_output=True)
    await diagnostics.log_context_usage(state)
    return responses, state


async def _approve_all_tools(tool_name: str, tool_input: dict[str, tp.Any], context: ToolPermissionContext) -> PermissionResultAllow:
    return PermissionResultAllow()


_STREAM_IDLE_TIMEOUT_MS = 300_000  # 5 minutes: abort stalled API streams
_COMPACT_TIMEOUT_S = 600.0  # day-sized contexts can take minutes to summarize


async def compact_session(*, state: vm.State) -> None:
    """Compact the live conversation in place and block until it finishes.

    The official Claude Agent SDK has no compact() method; the documented path is to send the
    `/compact` slash command as a query (code.claude.com/docs/en/agent-sdk/slash-commands). Manual
    /compact rewrites the same session, so resume keeps working and the dreamer can restart into
    the compacted conversation. The turn ends with SystemMessage(subtype="compact_boundary") then
    a ResultMessage; draining the response blocks until compaction completes. Bounded so a stuck
    summarization still lets the caller restart."""
    assert state.client is not None
    client = state.client
    await client.query("/compact")

    async def _drain() -> None:
        async for msg in client.receive_response():
            if isinstance(msg, SystemMessage) and msg.subtype == "compact_boundary":
                logger.client("Compaction boundary reached")

    await asyncio.wait_for(_drain(), timeout=_COMPACT_TIMEOUT_S)


def build_client_options(config: vm.VestaConfig, state: vm.State) -> ClaudeAgentOptions:
    memory_path = get_memory_path(config)
    if not memory_path.exists():
        raise FileNotFoundError(f"MEMORY.md not found at {memory_path}, cannot start agent without it")
    system_prompt = memory_path.read_text()

    # Constitution: a user-authored charter set from vestad and bind-mounted read-only,
    # so the agent cannot edit it. Prepend it ahead of MEMORY.md when non-empty.
    constitution_path = get_constitution_path(config)
    if constitution_path.exists():
        constitution = constitution_path.read_text().strip()
        if constitution:
            header = "# Constitution\n\nThe following was set by your user and is immutable. You cannot edit it.\n\n"
            system_prompt = f"{header}{constitution}\n\n{system_prompt}"

    # Personality voice: the shared rules + the active preset live in the personality skill
    # (agent-editable, the single source of truth for how the agent sounds). Loading them here,
    # in read-only core, makes the voice as unskippable as MEMORY.md: the agent drifts the
    # content by editing the skill files, but cannot remove this load. Picked up on next boot.
    personality_dir = config.skills_dir / "personality"
    voice_files = [personality_dir / "SKILL.md", personality_dir / "presets" / f"{config.agent_personality}.md"]
    voice = "\n\n".join(path.read_text().strip() for path in voice_files if path.exists())
    if voice:
        system_prompt = f"{system_prompt}\n\n# Active voice\n\nThis is how you sound.\n\n{voice}"

    os.environ.setdefault("CLAUDE_STREAM_IDLE_TIMEOUT_MS", str(_STREAM_IDLE_TIMEOUT_MS))

    # Scope ANTHROPIC_BASE_URL to the Claude Code subprocess only; mutating
    # os.environ here would leak the OpenRouter URL into every other subprocess
    # the agent spawns (skill CLIs, gh, git, ...) and silently misroute them.
    # message_processor only reaches here once the provider is authenticated (it idles otherwise), so a
    # provider is always present. Narrow the Optional for the type checker and fail loudly rather than
    # mis-build options if that invariant ever regresses.
    provider = config.provider
    if provider is None:
        raise RuntimeError("build_client_options reached with no authenticated provider")

    sdk_env: dict[str, str] = {}
    betas: list[str] = []
    # 1M-context beta and thinking are Anthropic-only; openrouter forces thinking disabled.
    thinking_config = ThinkingConfigDisabled(type="disabled")
    if isinstance(provider, vm.OpenRouterConfig):
        # The SDK always routes through the local caching proxy, never OpenRouter
        # directly. start_cache_proxy runs first in message_processor, so the URL is set.
        if not state.openrouter_proxy_url:
            raise RuntimeError("OpenRouter cache proxy not started before building client options")
        sdk_env["ANTHROPIC_BASE_URL"] = state.openrouter_proxy_url
        # The OpenRouter key + background model the subprocess talks to OpenRouter with, injected
        # from the config store (no shell env inheritance). The union guarantees the key.
        sdk_env["ANTHROPIC_AUTH_TOKEN"] = provider.key.get_secret_value()
        sdk_env["ANTHROPIC_SMALL_FAST_MODEL"] = OPENROUTER_SMALL_FAST_MODEL
        # Tell claude-code the model's real window so autocompact uses the right
        # threshold instead of its 200k default for non-Anthropic models.
        if state.openrouter_max_tokens:
            sdk_env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(state.openrouter_max_tokens)
    else:
        # Claude. The 1M-context beta unlocks windows above claude-code's 200k default.
        # Honor a user-chosen window: cap the autocompact threshold to it, and request the 1M
        # beta only when the choice needs the larger window. Unset keeps 1M beta on, no cap.
        chosen = provider.max_context_tokens
        if chosen is None or chosen > DEFAULT_CONTEXT_WINDOW:
            betas = [CONTEXT_1M_BETA]
        if chosen is not None:
            sdk_env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(chosen)
        thinking_config = provider.thinking

    # Context-usage % is reported by the official client's get_context_usage(), which measures
    # against the CLI's own window (set via CLAUDE_CODE_MAX_CONTEXT_TOKENS above); the headless
    # ClaudeAgentOptions has no context_window field, so nothing is passed here.
    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=provider.model,
        betas=betas,  # ty: ignore[invalid-argument-type]
        hooks=sdk_parsing.make_hooks(state),
        permission_mode="bypassPermissions",
        can_use_tool=_approve_all_tools,
        cwd=config.agent_dir,
        # "user" enables discovery of ~/.claude/skills, where the entrypoint symlinks every
        # installed skill (agent/skills/* + agent/core/skills/*); without it the Skill tool
        # never sees them. "project" stays for CLAUDE.md loading. skills="all" turns the
        # Skill tool on for every discovered skill (the single documented switch).
        setting_sources=["user", "project"],
        skills="all",
        add_dirs=[str(config.agent_dir), os.path.expanduser("~")],
        thinking=thinking_config,
        max_buffer_size=10 * 1024 * 1024,
        stderr=diagnostics.make_stderr_handler(state),
        mcp_servers={"vesta": build_vesta_tools_server(state, config)},
        resume=state.persisted.session_id,
        env=sdk_env,
    )
