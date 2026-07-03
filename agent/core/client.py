"""Conversation loop: builds queries, drives the SDK client, handles interrupts and dash-correction."""

import asyncio
import datetime as dt
import os
import time
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


_SILENCE_POLL_S = 15.0  # wake the turn's wait loop during quiet stretches to log liveness notes

# Post-interrupt wait for the interrupted turn's ResultMessage. Purely a labeling nicety so the
# next turn usually opens against a clean stream; when the CLI's wind-down outlives it, the
# consumer still receives everything and the late result is dropped as advisory (issue #958).
_INTERRUPT_TURN_END_GRACE_S = 5.0


async def _cancel_task(task: asyncio.Task[tp.Any]) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def _open_turn(state: vm.State, *, show_output: bool) -> vm.TurnSignals:
    turn = vm.TurnSignals(show_output=show_output)
    state.turn = turn
    return turn


def _close_turn(state: vm.State, turn: vm.TurnSignals) -> None:
    if state.turn is turn:
        state.turn = None


def _emit_text(text: str, *, state: vm.State) -> None:
    logger.assistant(text)
    state.event_bus.emit({"type": "assistant", "text": text})


def _emit_thinking(block: ThinkingBlock, *, state: vm.State) -> None:
    if not block.thinking.strip():
        return
    logger.thinking(block.thinking)
    state.event_bus.emit({"type": "thinking", "text": block.thinking, "signature": block.signature})


async def _dispatch_message(msg: Message, *, state: vm.State, config: vm.VestaConfig) -> None:
    """Handle one SDK stream message: emit content, persist session ids, detect auth loss, and
    close the open turn on its ResultMessage. Messages with no open turn (a self-initiated
    continuation turn, or an interrupted turn's wind-down) still emit — nothing is ever lost —
    and their ResultMessage is dropped."""
    diagnostics.touch_activity(state, "sdk_message")
    turn = state.turn
    if turn:
        turn.last_message_at = time.monotonic()
    if isinstance(msg, AssistantMessage):
        state.compacting = False
    if isinstance(msg, SystemMessage) and msg.subtype == "compact_boundary":
        logger.client("Compaction boundary reached")
    texts, thinking_blocks, session_id = sdk_parsing.parse_sdk_message(msg)
    if session_id and session_id != state.persisted.session_id:
        if state.persisted.session_id:
            logger.warning(f"Session ID changed: {state.persisted.session_id[:16]} -> {session_id[:16]} (resume may have failed)")
        persist_session_id(session_id, state=state, config=config)
    show = turn.show_output if turn else True
    if show:
        for block in thinking_blocks:
            _emit_thinking(block, state=state)
    text = "\n".join(texts) if texts else None
    if text:
        if turn:
            turn.texts.append(text)
        if show:
            filtered = sdk_parsing.filter_tool_lines(text)
            if filtered:
                _emit_text(filtered, state=state)
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
    if isinstance(msg, ResultMessage) or auth_lost:
        if turn and not turn.done.is_set():
            turn.done.set()
        elif isinstance(msg, ResultMessage):
            logger.debug("ResultMessage with no open turn (continuation or interrupted-turn wind-down); dropped")


async def consume_stream(*, state: vm.State, config: vm.VestaConfig) -> None:
    """Single long-lived consumer of the SDK stream — one per client session, connect to disconnect.

    Reading continuously is the fix for issue #958: with per-turn readers, messages left unconsumed
    after an abandoned interrupt drain filled the SDK's bounded buffer, blocking its reader task
    (jamming interrupt acks and control responses) and desyncing every later turn by one
    ResultMessage. Here nothing is ever left unconsumed, by construction."""
    assert state.client is not None
    client = state.client

    def _fail_open_turn(error: Exception) -> None:
        turn = state.turn
        if turn and not turn.done.is_set():
            turn.error = error
            turn.done.set()

    try:
        async for msg in client.receive_messages():
            await _dispatch_message(msg, state=state, config=config)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        # Stream death: surface it through the open turn so run_one's error handling restarts.
        # While idle, the next query() fails on the dead transport and takes the same path.
        logger.error(f"SDK stream consumer died: {type(e).__name__}: {e}")
        _fail_open_turn(e)
        return
    # Clean EOF mid-turn still means the CLI is gone; only consumer cancellation is a normal end.
    _fail_open_turn(RuntimeError("SDK stream ended"))


async def converse(prompt: str, *, state: vm.State, config: vm.VestaConfig, show_output: bool) -> list[str]:
    assert state.client is not None
    client = state.client

    query = sdk_parsing.build_query(prompt, timestamp=dt.datetime.now())
    diagnostics.touch_activity(state, "query_start")
    state.active_tools.clear()
    turn = _open_turn(state, show_output=show_output)
    try:
        await asyncio.wait_for(client.query(query), timeout=config.query_timeout)
    except TimeoutError:
        _close_turn(state, turn)
        await attempt_interrupt(state, config=config, reason="Query timeout")
        raise
    diagnostics.touch_activity(state, "query_sent")

    interrupt_task: asyncio.Task[tp.Any] | None = None
    if state.interrupt_event and not state.interrupt_event.is_set():
        interrupt_task = asyncio.create_task(state.interrupt_event.wait())

    done_task = asyncio.create_task(turn.done.wait())
    noted_silence: set[int] = set()

    try:
        while True:
            waitables: set[asyncio.Task[tp.Any]] = {done_task}
            if interrupt_task and not interrupt_task.done():
                waitables.add(interrupt_task)

            # Same silence budget as the old per-message wait: measured from the last stream
            # message (the consumer touches last_message_at), so quiet stretches still time out.
            # Wake at least every _SILENCE_POLL_S so long thinking gets liveness notes.
            silence_budget = config.response_timeout - (time.monotonic() - turn.last_message_at)
            wait_timeout = max(min(silence_budget, _SILENCE_POLL_S), 0)
            done, _ = await asyncio.wait(waitables, return_when=asyncio.FIRST_COMPLETED, timeout=wait_timeout)

            if not done:
                if time.monotonic() - turn.last_message_at >= config.response_timeout:
                    await attempt_interrupt(state, config=config, reason="Response timeout")
                    raise TimeoutError
                diagnostics.note_stream_silence(state, noted_at=noted_silence)
                continue

            if done_task in done:
                if turn.error is not None:
                    raise turn.error
                break

            await attempt_interrupt(state, config=config, reason="New message interrupt")
            # Give the wind-down a bounded window to deliver its ResultMessage so the next turn
            # usually opens clean; on expiry the consumer still receives everything (emitted live,
            # late result dropped), so nothing jams or leaks — the issue #958 failure mode.
            try:
                await asyncio.wait_for(turn.done.wait(), timeout=_INTERRUPT_TURN_END_GRACE_S)
            except TimeoutError:
                pass
            break
    finally:
        state.compacting = False
        _close_turn(state, turn)
        await _cancel_task(done_task)
        if interrupt_task and not interrupt_task.done():
            await _cancel_task(interrupt_task)

    return turn.texts


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
    the compacted conversation. The turn ends with SystemMessage(subtype="compact_boundary") — the
    stream consumer logs it — then a ResultMessage, which closes the turn; waiting on the turn
    blocks until compaction completes. Bounded so a stuck summarization still lets the caller
    restart."""
    assert state.client is not None
    client = state.client
    turn = _open_turn(state, show_output=False)
    try:
        await client.query("/compact")
        await asyncio.wait_for(turn.done.wait(), timeout=_COMPACT_TIMEOUT_S)
        if turn.error is not None:
            raise turn.error
    finally:
        _close_turn(state, turn)


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
