"""Conversation loop: builds queries, drives the SDK client, handles preemption and dash-correction."""

import asyncio
import contextlib
import datetime as dt
import json
import os
import pathlib as pl
import time
import typing as tp

import aiohttp
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    Message,
    RateLimitEvent,
    ResultMessage,
    ThinkingBlock,
)
from claude_agent_sdk.types import PermissionResultAllow, SdkBeta, ThinkingConfigDisabled, ToolPermissionContext

from . import config as cfg
from . import diagnostics, logger, sdk_parsing, state_store, vestad_client
from . import models as vm
from .config import CONTEXT_1M_BETA, DEFAULT_CONTEXT_WINDOW
from .events import ModelAccessEvent, model_access_info
from .helpers import get_constitution_path, get_memory_path
from .provider import (
    OPENROUTER_SMALL_FAST_MODEL,
    TERMINAL_PROVIDER_ERRORS,
    active_cooldown,
    is_terminal_auth_error,
    is_unauthenticated,
    observed_provider_failure,
    rate_limit_cooldown,
)
from .tools import build_vesta_tools_server

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# The error surface of a dead or wedged CLI subprocess, caught by every consumer of the SDK seam
# (the session open below, loops.py's turn and compaction error handlers). Owned here so loops.py
# never imports claude_agent_sdk itself.
SDK_ERRORS: tuple[type[Exception], ...] = (ClaudeSDKError, OSError, RuntimeError)


def model_access_available(state: vm.State, *, now: float | None = None) -> bool:
    return active_cooldown(state.persisted.provider_cooldown, now=now) is None


def _model_access_event(state: vm.State) -> ModelAccessEvent:
    cooldown = active_cooldown(state.persisted.provider_cooldown)
    return {"type": "model_access", **model_access_info(cooldown)}


async def wait_for_model_access(*, state: vm.State, config: cfg.VestaConfig) -> bool:
    cooldown = active_cooldown(state.persisted.provider_cooldown)
    if cooldown is None:
        if state.persisted.provider_cooldown is not None:
            state.persisted.provider_cooldown = None
            await state_store.save_state_async(state.persisted, config)
            state.event_bus.emit(_model_access_event(state))
        return True
    timeout = max(cooldown.until - time.time(), 0)
    try:
        await asyncio.wait_for(state.shutdown_event.wait(), timeout=timeout)
        return False
    except TimeoutError:
        state.persisted.provider_cooldown = None
        await state_store.save_state_async(state.persisted, config)
        state.event_bus.emit(_model_access_event(state))
        return True


async def resolve_openrouter_max_tokens(config: cfg.VestaConfig) -> int | None:
    """Look up the OpenRouter model's real context window. claude-code assumes a
    200k window for non-Anthropic models (claude-code#46416), so the value passed
    via CLAUDE_CODE_MAX_CONTEXT_TOKENS must reflect what the model actually supports.
    The caller caps this at config.provider.max_context_tokens before passing it to the SDK
    (cache-read cost scales with context size). Returns None on any failure, so
    claude-code falls back to its default, same behavior as before."""
    if not isinstance(config.provider, cfg.OpenRouterConfig):
        return None
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                OPENROUTER_MODELS_URL,
                headers={"Authorization": f"Bearer {config.provider.key.get_secret_value()}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp,
        ):
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


async def attempt_interrupt(state: vm.State, *, config: cfg.VestaConfig, reason: str) -> bool:
    """Hard-abort the current turn via the SDK's interrupt control request.

    In headless mode the CLI's handler for this request also kills every running backgrounded
    subagent/workflow task (issue #982), so routine preemption is send_preempt instead; this
    fires only on failure paths (silence/query timeout, provider auth lost)."""
    client = state.client
    if not client:
        return False

    try:
        await asyncio.wait_for(client.interrupt(), timeout=config.interrupt_timeout)
        logger.debug(f"Interrupt sent: {reason}")
        return True
    except TimeoutError:
        # The SDK didn't ack the interrupt within the window. Log + emit but don't kill the
        # process: in practice this fires more often during heavy thinking or a long-running
        # tool than during a real hang, and converse's response-timeout path already ends a
        # genuinely dead turn (TimeoutError -> restart).
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


async def send_preempt(prompt: str, *, state: vm.State, config: cfg.VestaConfig) -> bool:
    """Deliver `prompt` into the live session as a priority:"now" user message (the envelope
    and its protocol story live in sdk_parsing.build_priority_now_message). A foreground tool
    call already executing is not cut short: the abort latches and applies when the tool
    returns, so the preempt is delayed by at most that tool's remaining runtime, never lost.

    A True return is the end of the prompt's lifecycle. The CLI persists the message into the
    session on receipt (a crash-restart resumes with it in context) and its output streams
    through the session's single consumer, but it guarantees no per-prompt ResultMessage: it
    merges rapid queued prompts into one turn, starts turns of its own (background task
    notifications), and its results carry no prompt identity. Counting-based turn pairing on
    top of that wedged a turn on a merged-away result and crashed the agent (incident
    2026-07-14, agent luna), so the caller consumes the item at delivery and never opens a
    Vesta turn for it. The open turn is marked `preempted` for reply-completeness consumers
    (the dash correction).

    Returns False without sending when there is nothing to preempt (no client, no open turn),
    when preemption is barred (boot turn, compaction in flight, unauthenticated provider), or
    on a failed write; the caller then queues the prompt as an ordinary turn."""
    client = state.client
    turn = state.turn
    if not client or turn is None or state.noninterruptible_turn_active or state.compacting:
        return False
    if is_unauthenticated(state.provider_status) or not model_access_available(state):
        # Same deferral as the processor's gate: don't hand prompts to a dead token; the
        # notification file stays on disk and re-runs after re-auth.
        return False

    message = sdk_parsing.build_priority_now_message(prompt, timestamp=dt.datetime.now())

    async def _one() -> tp.AsyncIterator[dict[str, tp.Any]]:
        yield message

    try:
        # A single stdin write: bound it like an interrupt, not like a query. On timeout the
        # caller queues plain and nothing is lost.
        await asyncio.wait_for(client.query(_one()), timeout=config.interrupt_timeout)
        turn.preempted = True
        logger.debug("Preempt sent (priority=now)")
        return True
    except Exception as e:
        # Like attempt_interrupt: best-effort, broad catch. A failed preempt must never abort
        # the notification/message that asked for it; the prompt still queues and runs.
        logger.error(f"Preempt send failed: {e} | {diagnostics.format_hang_diagnostics(state)}")
        return False


async def persist_session_id(session_id: str, *, state: vm.State, config: cfg.VestaConfig) -> None:
    state.persisted.session_id = session_id
    await state_store.save_state_async(state.persisted, config)
    logger.debug(f"Captured session_id: {session_id[:16]}...")


_SILENCE_POLL_S = 10.0  # wake the turn's wait loop during quiet stretches to log liveness notes


async def cancel_task(task: asyncio.Task[tp.Any]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


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


def _emit_parsed_content(texts: list[str], thinking_blocks: list[ThinkingBlock], error_texts: list[str], *, state: vm.State) -> None:
    """Emit one message's parsed content: thinking + speech (respecting the turn's show_output),
    and CLI-synthesized error text through the error channel."""
    turn = state.turn
    show = turn.show_output if turn else True
    if show:
        for block in thinking_blocks:
            _emit_thinking(block, state=state)
    text = "\n".join(texts) if texts else None
    if turn and (text or thinking_blocks):
        turn.last_visible_at = time.monotonic()
    if text:
        if turn:
            turn.texts.append(text)
        if show:
            filtered = sdk_parsing.filter_tool_lines(text)
            if filtered:
                _emit_text(filtered, state=state)
    for error_text in error_texts:
        # CLI-synthesized error text is kept out of Vesta's speech by parse_sdk_message; surface
        # the failure through the error channel instead so a failed turn is never silent in the app.
        state.event_bus.emit({"type": "error", "text": f"Turn failed upstream: {error_text[:500]}"})


async def _note_rate_limit(msg: RateLimitEvent, *, state: vm.State, config: cfg.VestaConfig) -> None:
    """Surface a rejected rate limit from the structured classification: the CLI's synthesized text
    for the same event misnames the window (issue #1071), so this event is what consumers trust.
    Once per window; the type/resets_at pair changes when a different limit trips. The internal event
    is kept for history; a best-effort user notification raises a user-facing toast + push."""
    info = msg.rate_limit_info
    notice = sdk_parsing.rate_limit_notice(info, now=time.time())
    window_key = (info.rate_limit_type, info.resets_at)
    if notice:
        state.persisted.provider_cooldown = rate_limit_cooldown(resets_at=info.resets_at, window=info.rate_limit_type)
        state.current_turn_rate_limited = True
        await state_store.save_state_async(state.persisted, config)
        state.event_bus.emit(_model_access_event(state))
    if notice and window_key != state.rate_limit_noticed:
        state.rate_limit_noticed = window_key
        state.event_bus.emit({"type": "rate_limited", "text": notice, "window": info.rate_limit_type, "resets_at": info.resets_at})
        agent_name = os.environ["AGENT_NAME"] if "AGENT_NAME" in os.environ else "Vesta"
        await vestad_client.send_user_notification("rate_limited", agent_name, notice)


async def _dispatch_message(msg: Message, *, state: vm.State, config: cfg.VestaConfig) -> None:
    """Handle one SDK stream message: emit content, persist session ids, detect auth loss, and
    close the open turn on its ResultMessage. Messages with no open turn (a delivered preempt
    running as its own turn, a CLI-initiated continuation, or an interrupted turn's wind-down)
    still emit, nothing is ever lost, and their ResultMessage is dropped."""
    diagnostics.touch_activity(state, "sdk_message")
    turn = state.turn
    if turn:
        turn.last_message_at = time.monotonic()
    # Turnless CLI activity (a delivered preempt running as its own turn, or a
    # CLI-initiated turn such as a background task notification): keep the activity state
    # honest, since it drives the snoozed-batch flush and the proactive-check gate.
    elif isinstance(msg, AssistantMessage):
        state.event_bus.set_state("thinking")
    elif isinstance(msg, ResultMessage):
        state.event_bus.set_state("idle")
    if isinstance(msg, AssistantMessage):
        state.compacting = False
    # The CLI ticks a thinking counter while the model reasons; diagnostics turns it into the
    # turn's liveness narrative ("Thinking..." on the first tick, interval notes from the wait loop).
    thinking_estimate = sdk_parsing.thinking_tokens_estimate(msg)
    if turn and thinking_estimate is not None:
        diagnostics.note_thinking_tick(turn, tokens=thinking_estimate)
    texts, thinking_blocks, session_id, error_texts = sdk_parsing.parse_sdk_message(msg)
    if session_id and session_id != state.persisted.session_id:
        if state.persisted.session_id:
            logger.warning(f"Session ID changed: {state.persisted.session_id[:16]} -> {session_id[:16]} (resume may have failed)")
        await persist_session_id(session_id, state=state, config=config)
    _emit_parsed_content(texts, thinking_blocks, error_texts, state=state)
    if isinstance(msg, RateLimitEvent):
        await _note_rate_limit(msg, state=state, config=config)
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
            logger.debug("ResultMessage with no open turn (continuation or CLI-initiated turn); dropped")


async def consume_stream(*, state: vm.State, config: cfg.VestaConfig) -> None:
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


@contextlib.asynccontextmanager
async def client_session(*, state: vm.State, config: cfg.VestaConfig) -> tp.AsyncIterator[ClaudeSDKClient]:
    """The SDK session lifecycle, owned end to end: build options, open the client, spawn the single
    stream consumer for the session, and on exit cancel the consumer and reset the session fields.

    A failed open with a persisted session_id is retried once on a fresh session (the CLI errors at
    startup when the resumed session file is gone); the second failure, or any failure with nothing
    to resume, propagates to the caller."""
    options = build_client_options(config, state)
    retried = False
    while True:
        opened = False
        try:
            async with ClaudeSDKClient(options=options) as client:
                opened = True
                state.client = client
                # The one consumer of the SDK stream for this whole session (see consume_stream);
                # turn drivers only wait on state.turn signals, they never read the stream.
                consumer_task = asyncio.create_task(consume_stream(state=state, config=config))
                logger.client("Client session started")
                try:
                    yield client
                finally:
                    await cancel_task(consumer_task)
                    state.client = None
                    state.compacting = False
                    state.turn = None
                    logger.client("Client session closed")
            return
        except SDK_ERRORS as exc:
            if opened or retried or not state.persisted.session_id:
                raise
            await asyncio.sleep(0.05)  # give stderr handler time to drain buffered subprocess output
            exit_code, stderr_tail = diagnostics.format_crash_detail(exc, state.stderr_buffer)
            logger.warning(
                f"Session resume failed ({state.persisted.session_id[:16]}...): {type(exc).__name__}: {exc}"
                f" | exit_code={exit_code}"
                f", starting fresh\nRecent stderr:\n{stderr_tail}"
            )
            state.persisted.session_id = None
            await state_store.save_state_async(state.persisted, config)
            state.stderr_buffer.clear()
            options = build_client_options(config, state)
            retried = True


class QueryNotDeliveredError(Exception):
    """The query never reached the CLI: the send timed out, or client.query() raised on a dead
    transport. The caller must keep the notification file that fed this turn (the resumed session
    never saw the message), unlike a post-delivery failure (response timeout, stream death) where
    deletion stays correct because the session already contains it."""


async def converse(prompt: str, *, state: vm.State, config: cfg.VestaConfig, show_output: bool) -> vm.TurnSignals:
    """Drive one plain turn: send the query and wait for the result that closes it. Sound
    because plain turns are self-serializing (one query in flight, then wait). Delivered
    preempts never come through here; send_preempt's True return is their whole lifecycle.
    A preempt landing mid-turn needs no handling: the CLI-side abort ends this turn as an
    ordinary ResultMessage."""
    assert state.client is not None
    if not await wait_for_model_access(state=state, config=config):
        raise asyncio.CancelledError
    client = state.client

    diagnostics.touch_activity(state, "query_start")
    state.active_tools.clear()
    turn = _open_turn(state, show_output=show_output)
    query = sdk_parsing.build_query(prompt, timestamp=dt.datetime.now())
    try:
        await asyncio.wait_for(client.query(query), timeout=config.query_timeout)
    except TimeoutError:
        _close_turn(state, turn)
        await attempt_interrupt(state, config=config, reason="Query timeout")
        raise QueryNotDeliveredError("query timed out before the CLI received it") from None
    except Exception as e:
        # query() surfaces SDK/transport failures across a wide, loosely typed error surface
        # (see attempt_interrupt above): catch broadly; like a send timeout this means the CLI
        # never got the prompt.
        _close_turn(state, turn)
        raise QueryNotDeliveredError(str(e) or type(e).__name__) from e
    diagnostics.touch_activity(state, "query_sent")

    done_task = asyncio.create_task(turn.done.wait())

    try:
        while True:
            # Same silence budget as the old per-message wait: measured from the last stream
            # message (the consumer touches last_message_at), so quiet stretches still time out.
            # Wake at least every _SILENCE_POLL_S so long thinking gets liveness notes.
            silence_budget = config.response_timeout - (time.monotonic() - turn.last_message_at)
            wait_timeout = max(min(silence_budget, _SILENCE_POLL_S), 0)
            done, _ = await asyncio.wait({done_task}, timeout=wait_timeout)

            if not done:
                if time.monotonic() - turn.last_message_at >= config.response_timeout:
                    await attempt_interrupt(state, config=config, reason="Response timeout")
                    raise TimeoutError
                diagnostics.note_turn_liveness(state, turn=turn)
                continue

            if turn.error is not None:
                raise turn.error
            break
    finally:
        state.compacting = False
        _close_turn(state, turn)
        await cancel_task(done_task)

    return turn


_EM_DASH = "—"
_EN_DASH = "\u2013"  # en dash
_DASH_WARNING = (
    "[System: your last response contained an em dash, en dash, or ' - ' used as a separator. "
    "Never use these. Use commas, periods, colons, or restructure the sentence. "
    "Resend your last message without them.]"
)


def _contains_dashes(texts: list[str]) -> bool:
    return any(_EM_DASH in t or _EN_DASH in t or " - " in t for t in texts)


async def process_message(msg: str, *, state: vm.State, config: cfg.VestaConfig) -> tuple[list[str], vm.State]:
    turn = await converse(msg, state=state, config=config, show_output=True)
    if config.block_dashes and turn.texts and _contains_dashes(turn.texts) and not turn.preempted:
        # A preempted turn's reply was cut short at a step boundary; correcting a truncated
        # reply would re-send it after the preempting prompt's work, so skip it.
        logger.warning("Em/en dash detected in response, sending correction")
        await converse(_DASH_WARNING, state=state, config=config, show_output=True)
    await diagnostics.log_context_usage(state)
    return turn.texts, state


async def _approve_all_tools(_tool_name: str, _tool_input: dict[str, tp.Any], _context: ToolPermissionContext) -> PermissionResultAllow:
    return PermissionResultAllow()


_STREAM_IDLE_TIMEOUT_MS = 300_000  # 5 minutes: abort stalled API streams
_COMPACT_TIMEOUT_S = 600.0  # day-sized contexts can take minutes to summarize


def _read_compaction_summary(session_id: str) -> str | None:
    """Best-effort: pull the latest /compact summary text from the CLI's session transcript, for
    logging. The summary is written to ~/.claude/projects/<encoded-cwd>/<session_id>.jsonl (tagged
    isCompactSummary), not streamed, so we glob by session_id to avoid reconstructing the cwd
    encoding. The transcript format is undocumented, so any failure just returns None."""
    try:
        matches = sorted(pl.Path.home().glob(f".claude/projects/*/{session_id}.jsonl"))
        if not matches:
            return None
        text: str | None = None
        for line in matches[-1].read_text().splitlines():
            entry = json.loads(line)
            if not (entry.get("isCompactSummary")):
                continue
            if "message" not in entry or "content" not in entry["message"]:
                continue
            content = entry["message"]["content"]
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                parts = [block["text"] for block in content if isinstance(block, dict) and "text" in block]
                text = "\n".join(parts) if parts else text
        return text
    except (OSError, ValueError, KeyError, TypeError):
        return None


async def compact_session(*, state: vm.State, config: cfg.VestaConfig, prompt: str | None = None) -> None:
    """Compact the live conversation in place and block until it finishes.

    The official Claude Agent SDK has no compact() method; the documented path is to send the
    `/compact` slash command as a query (code.claude.com/docs/en/agent-sdk/slash-commands). Text
    after the command is passed to the summarizer as guidance (a caller's curated prompt). Manual
    /compact rewrites the same session, so resume keeps working and the dreamer can restart into
    the compacted conversation. The turn ends with SystemMessage(subtype="compact_boundary") — the
    stream consumer logs it — then a ResultMessage, which closes the turn; waiting on the turn
    blocks until compaction completes. Bounded so a stuck summarization still lets the caller
    restart."""
    assert state.client is not None
    client = state.client
    turn = _open_turn(state, show_output=False)
    try:
        # A slash command is a single line: collapse whitespace so multi-line guidance (e.g. an
        # appended draft) reaches the summarizer intact instead of being truncated at the first newline.
        # The send is a stdin write to the CLI subprocess: bound it like every other query so a wedged
        # CLI fails the compaction instead of wedging the message processor.
        query = "/compact" if prompt is None else f"/compact {' '.join(prompt.split())}"
        await asyncio.wait_for(client.query(query), timeout=config.query_timeout)
        await asyncio.wait_for(turn.done.wait(), timeout=_COMPACT_TIMEOUT_S)
        if turn.error is not None:
            raise turn.error
        # Surface what the compaction produced: the summary is written to the session transcript,
        # not streamed, so read it back for the log (best-effort, never fatal).
        if state.persisted.session_id:
            summary = await asyncio.to_thread(_read_compaction_summary, state.persisted.session_id)
            if summary:
                logger.client(f"Compaction summary ({len(summary)} chars):\n{summary}")
    finally:
        _close_turn(state, turn)


def build_client_options(config: cfg.VestaConfig, state: vm.State) -> ClaudeAgentOptions:
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
    betas: list[SdkBeta] = []
    # 1M-context beta and thinking are Anthropic-only; openrouter forces thinking disabled.
    thinking_config = ThinkingConfigDisabled(type="disabled")
    if isinstance(provider, cfg.OpenRouterConfig):
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
        betas=betas,
        hooks=sdk_parsing.make_hooks(state),
        permission_mode="bypassPermissions",
        can_use_tool=_approve_all_tools,
        cwd=config.agent_dir,
        # "user" enables discovery of ~/.claude/skills, where agent startup symlinks active
        # optional skills plus every core skill; without it the Skill tool
        # never sees them. "project" stays for CLAUDE.md loading. skills="all" turns the
        # Skill tool on for every discovered skill (the single documented switch).
        setting_sources=["user", "project"],
        skills="all",
        add_dirs=[str(config.agent_dir), str(pl.Path.home())],
        thinking=thinking_config,
        max_buffer_size=10 * 1024 * 1024,
        stderr=diagnostics.make_stderr_handler(state),
        mcp_servers={"vesta": build_vesta_tools_server(state, config)},
        resume=state.persisted.session_id,
        env=sdk_env,
    )
