"""Notification batch triage via a one-shot sub-agent.

Runs a stateless query over a batch of passive notifications and returns
either a tight filtered summary or None when nothing is worth surfacing.
On any failure the caller falls back to the raw batch (current behavior),
so this module is strictly additive: at worst it does nothing.
"""

import asyncio
import datetime as dt
import os
import pathlib as pl

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    TextBlock,
    query,
)

from . import logger
from . import models as vm


TRIAGE_TIMEOUT = 30  # seconds; on hit, fall back to raw flush
TRIAGE_MAX_TURNS = 1  # one shot, no follow-ups
SUPPRESSED_LOG = pl.Path("/root/agent/logs/triage-suppressed.log")


TRIAGE_SYSTEM = """You are a notification triage filter for an AI agent named okami serving Lucio.

Your only job: read a batch of incoming notifications and decide what is worth surfacing to the main agent. You do not reply to anyone, you do not call tools. You return a single text response.

DROP (output should not mention these):
- WhatsApp status updates (chat_name=status)
- Marketing newsletters and promotional emails (Booking, GoPro, Audible, IMDb, Genelec, LinkedIn job alerts, The Independent, Telegraph, Guardian Jobs, TIME, The Information, TreeSize, Academia Mentions, GitHub digest, etc.)
- News channel broadcasts (Unione Sarda, La Gazzetta dello Sport, etc.)
- Generic group chat banter unrelated to active projects (food pics, weather small talk, general chatter)
- Recipe spam, generic forwards
- Idle pings (source=context, type=user_idle)
- WhatsApp reactions (👍, 🙏 etc) unless on a thread the main agent is actively engaged in
- Microsoft 365 quarantine notices and similar automated mail

SURFACE (include in output):
- Direct questions to Lucio
- Messages mentioning active project keywords: WALLS, workshop, audiogen, andalusia, NURNET, alhambra, mezquita, sevilla, cordoba, granada, nuragic
- Messages from close family or business contacts that need Lucio's attention or action
- Hotel, booking, reservation, or travel updates relevant to the current trip
- Errors, alerts, or system notifications requiring attention (backup failures, container issues, GitHub PR/issue notifications about elyxlz/vesta)
- Anything addressed directly to Lucio or quoting him
- The "guide" trigger from Lucio in the Andalusia group (this is hot, surface it immediately)

OUTPUT FORMAT:
- If nothing is worth surfacing: output exactly `NOTHING` and nothing else.
- Otherwise: 1 to N short lines, one per surfaced item, in the format `[source/contact] short actionable substance`.
- No preamble, no closing, no explanation. Just the summary.

Be ruthless. Better to drop a marginal item than pollute the main agent's context. The main agent re-reads conversation history when needed; missing one filtered item is recoverable."""


def _build_user_prompt(notifications: list[vm.Notification], current_context: str) -> str:
    parts = []
    if current_context:
        parts.append(f"CURRENT CONVERSATION CONTEXT:\n{current_context}")
    body = "\n".join(n.format_for_display() for n in notifications)
    parts.append(f"NOTIFICATIONS BATCH ({len(notifications)} items):\n{body}")
    parts.append("Output: filtered summary or `NOTHING`.")
    return "\n\n".join(parts)


def _log_suppressed(notifications: list[vm.Notification], reason: str = "filtered") -> None:
    """Append the raw batch to a suppression log so over-suppression is auditable."""
    try:
        SUPPRESSED_LOG.parent.mkdir(parents=True, exist_ok=True)
        with SUPPRESSED_LOG.open("a", encoding="utf-8") as f:
            f.write(f"\n--- {dt.datetime.now().isoformat()} reason={reason} count={len(notifications)} ---\n")
            for n in notifications:
                f.write(n.format_for_display() + "\n")
    except OSError as e:
        logger.warning(f"triage: could not write suppression log: {e}")


async def triage_batch(
    notifications: list[vm.Notification],
    *,
    current_context: str = "",
    model: str | None = None,
) -> str | None:
    """Run a triage sub-agent over a batch of passive notifications.

    Returns:
        - None if nothing is worth surfacing (the main agent gets nothing)
        - A formatted summary string to inject as a single passive prompt
        - Raises nothing; on internal failure returns the raw batch as a fallback
    """
    if not notifications:
        return None

    user_prompt = _build_user_prompt(notifications, current_context)
    options = ClaudeAgentOptions(
        system_prompt=TRIAGE_SYSTEM,
        max_turns=TRIAGE_MAX_TURNS,
        allowed_tools=[],
        tools=[],
        permission_mode="bypassPermissions",
        model=model,
        thinking={"type": "disabled"},
        effort="low",
        extra_args={"thinking-display": "omitted"},
    )

    response_text = ""
    try:

        async def _run() -> str:
            text = ""
            async for msg in query(prompt=user_prompt, options=options):
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            text += block.text
            return text.strip()

        response_text = await asyncio.wait_for(_run(), timeout=TRIAGE_TIMEOUT)
    except TimeoutError:
        logger.error(f"triage: timeout after {TRIAGE_TIMEOUT}s, falling back to raw flush")
        return _format_raw_fallback(notifications)
    except Exception as e:
        logger.error(f"triage: failed ({type(e).__name__}: {e}), falling back to raw flush")
        return _format_raw_fallback(notifications)

    response_text = response_text.strip()
    if not response_text or response_text.upper() == "NOTHING":
        _log_suppressed(notifications, reason="all-dropped")
        logger.client(f"triage: dropped {len(notifications)} notif(s) as noise")
        return None

    _log_suppressed(notifications, reason="filtered")
    logger.client(f"triage: surfaced {response_text.count(chr(10)) + 1} item(s) from {len(notifications)} notif(s)")
    return f"<notifications>\n{response_text}\n</notifications>"


def _format_raw_fallback(notifications: list[vm.Notification]) -> str:
    """Emit the raw batch when triage fails. Equivalent to current behavior."""
    body = "\n".join(n.format_for_display() for n in notifications)
    return f"<notifications>\n{body}\n</notifications>"


def is_enabled() -> bool:
    """Triage layer can be hard-disabled via env var without code changes."""
    return os.environ.get("OKAMI_PASSIVE_TRIAGE", "1") not in ("0", "false", "False", "")
