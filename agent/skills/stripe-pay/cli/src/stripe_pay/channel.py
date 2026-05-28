"""User-channel abstraction.

The skill must ask the user before every charge, on whatever channel the user
prefers. We auto-detect that from ``MEMORY.md`` (the "Primary Channel" section),
then send the prompt + poll for a reply.

Currently supported: WhatsApp, Telegram, app-chat. Default fallback: WhatsApp.

The pattern is intentionally CLI-shelling (rather than importing each channel's
Python library) so this skill stays decoupled from any one channel's
implementation. Each channel ships its own ``<name>`` binary.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


Channel = Literal["whatsapp", "telegram", "app-chat"]
DEFAULT_CHANNEL: Channel = "whatsapp"

# Words that count as approval / rejection. Lowercased before comparing.
APPROVE_WORDS = {"yes", "y", "go", "ok", "okay", "confirm", "approve", "approved"}
APPROVE_EMOJIS = {"\U0001f44d", "✅", "✓"}  # 👍 ✅ ✓
REJECT_WORDS = {"no", "n", "stop", "cancel", "deny", "denied", "reject", "rejected"}
REJECT_EMOJIS = {"\U0001f44e", "❌"}  # 👎 ❌


@dataclass(frozen=True)
class Reply:
    """Outcome of a poll for the user's reply."""

    decision: Literal["approve", "reject", "timeout"]
    raw_text: str | None = None


# ---------------------------------------------------------------------------
# Channel detection
# ---------------------------------------------------------------------------


def detect_primary_channel(memory_file: Path | None = None) -> Channel:
    """Parse ``MEMORY.md`` and return the user's primary channel.

    Falls back to WhatsApp if the file is absent or unparseable. We look for a
    line under a heading containing "Primary Channel" that mentions one of the
    supported channels (case-insensitive).
    """
    candidates = (
        [memory_file]
        if memory_file
        else [
            Path.home() / "agent" / "MEMORY.md",
            Path.home() / "MEMORY.md",
        ]
    )
    for path in candidates:
        if not path or not path.exists():
            continue
        try:
            text = path.read_text()
        except OSError:
            continue
        section = _extract_primary_channel_section(text)
        if not section:
            continue
        chosen = _pick_channel_from_section(section)
        if chosen:
            return chosen
    return DEFAULT_CHANNEL


def _pick_channel_from_section(section: str) -> Channel | None:
    """Pick a channel from the Primary Channel section text.

    Prefers the channel mentioned right after a "Default" marker. Falls back
    to whichever supported channel name appears first in the text.
    """
    aliases: dict[str, Channel] = {
        "whatsapp": "whatsapp",
        "telegram": "telegram",
        "app-chat": "app-chat",
        "app chat": "app-chat",
    }
    lowered = section.lower()

    # 1. Strong signal: "**Default**: <Channel>" (or "Default: <Channel>") —
    #    the channel that follows the Default marker wins.
    default_match = re.search(r"\*?\*?default\*?\*?\s*:\s*(.+)", lowered)
    if default_match:
        tail = default_match.group(1)
        for alias, channel in aliases.items():
            if alias in tail.split(".", 1)[0]:  # only the first sentence
                return channel

    # 2. Fallback: pick whichever supported alias appears first by position.
    best: tuple[int, Channel] | None = None
    for alias, channel in aliases.items():
        idx = lowered.find(alias)
        if idx == -1:
            continue
        if best is None or idx < best[0]:
            best = (idx, channel)
    return best[1] if best else None


def _extract_primary_channel_section(memory_text: str) -> str | None:
    """Return the lines under the 'Primary Channel' heading, or None."""
    pattern = re.compile(
        r"#{1,6}\s*Primary Channel\b.*?(?=\n#{1,6}\s|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(memory_text)
    return m.group(0) if m else None


# ---------------------------------------------------------------------------
# Send + wait
# ---------------------------------------------------------------------------


def send_prompt(channel: Channel, message: str) -> dict:
    """Send ``message`` to the user via ``channel``.

    Returns a dict with at minimum ``{"sent_at": <unix-ts>}``. Raises
    ``ChannelError`` on failure.
    """
    sent_at = time.time()
    if channel == "whatsapp":
        _shell(["whatsapp", "send", "self", message])
    elif channel == "telegram":
        _shell(["telegram", "send", "self", message])
    elif channel == "app-chat":
        _shell(["app-chat", "send", message])
    else:
        raise ChannelError(f"unsupported channel: {channel}")
    return {"sent_at": sent_at, "channel": channel}


def wait_for_reply(
    channel: Channel,
    sent_at: float,
    timeout_s: int = 300,
    poll_s: int = 5,
) -> Reply:
    """Poll the channel's inbound log until the user replies or we time out.

    ``sent_at`` is the unix timestamp of when we sent the prompt — only
    messages newer than that count as a reply. ``timeout_s`` defaults to 5
    minutes.
    """
    deadline = sent_at + timeout_s
    while time.time() < deadline:
        reply_text = _latest_reply(channel, sent_at)
        if reply_text is not None:
            decision = classify_reply(reply_text)
            if decision in ("approve", "reject"):
                return Reply(decision=decision, raw_text=reply_text)
            # Anything else — keep waiting; the user might be writing a
            # clarifying question and will follow up with yes/no.
        time.sleep(poll_s)
    return Reply(decision="timeout")


def classify_reply(text: str) -> Literal["approve", "reject", "unknown"]:
    """Bucket a reply into approve / reject / unknown."""
    stripped = text.strip().lower()
    if not stripped:
        return "unknown"
    # Emoji check (look at the raw text, not lowered, to be safe).
    raw = text.strip()
    if any(e in raw for e in APPROVE_EMOJIS):
        return "approve"
    if any(e in raw for e in REJECT_EMOJIS):
        return "reject"
    # First word match — be forgiving about trailing punctuation.
    first = re.split(r"[\s,.!?]", stripped, maxsplit=1)[0]
    if first in APPROVE_WORDS:
        return "approve"
    if first in REJECT_WORDS:
        return "reject"
    return "unknown"


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


class ChannelError(RuntimeError):
    """Raised when a channel CLI is missing or returns a non-zero exit."""


def _shell(cmd: list[str]) -> str:
    """Run ``cmd`` and return stdout. Raise ChannelError on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError as e:
        raise ChannelError(f"channel binary not found: {cmd[0]} — install / authenticate that skill first") from e
    except subprocess.TimeoutExpired as e:
        raise ChannelError(f"{cmd[0]} timed out") from e
    if result.returncode != 0:
        raise ChannelError(f"{' '.join(cmd[:2])} exit={result.returncode}: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def _latest_reply(channel: Channel, after_ts: float) -> str | None:
    """Return the body of the user's latest inbound message after ``after_ts``.

    None if no fresh message yet. The implementation differs by channel because
    each CLI exposes a different list-messages contract; we keep one parser per
    channel and return ``None`` on any unexpected shape (treated as "still
    waiting" rather than crashing the charge).
    """
    try:
        if channel == "whatsapp":
            out = _shell(["whatsapp", "list-messages", "self", "--limit", "5"])
            return _pick_latest_inbound(out, after_ts, key_ts="timestamp", key_body="content", key_dir="is_from_me")
        if channel == "telegram":
            out = _shell(["telegram", "list-messages", "self", "--limit", "5"])
            return _pick_latest_inbound(out, after_ts, key_ts="timestamp", key_body="content", key_dir="is_from_me")
        if channel == "app-chat":
            out = _shell(["app-chat", "list-messages", "--limit", "5"])
            return _pick_latest_inbound(out, after_ts, key_ts="ts", key_body="text", key_dir="from_agent")
    except ChannelError:
        # Transient — caller will poll again.
        return None
    return None


def _pick_latest_inbound(
    raw_json: str,
    after_ts: float,
    *,
    key_ts: str,
    key_body: str,
    key_dir: str,
) -> str | None:
    """Best-effort parse of a channel's list-messages JSON into a reply body.

    Channels we wrap return a list of message dicts. We:
      - reject messages older than ``after_ts``
      - reject outbound messages (where ``msg[key_dir]`` is truthy for whatsapp/
        telegram or true for ``from_agent`` in app-chat)
      - return the body of the newest remaining one
    """
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, dict):
        # Some CLIs wrap in {"messages": [...]} — be tolerant.
        data = data.get("messages") or data.get("data") or []
    if not isinstance(data, list):
        return None

    candidates = []
    for msg in data:
        if not isinstance(msg, dict):
            continue
        ts = msg.get(key_ts)
        # ts may be unix-seconds, unix-ms, or an ISO string; coerce best we can.
        ts_seconds = _coerce_ts(ts)
        if ts_seconds is None or ts_seconds <= after_ts:
            continue
        # Skip our own outbound message.
        if msg.get(key_dir):
            continue
        body = msg.get(key_body)
        if isinstance(body, str) and body.strip():
            candidates.append((ts_seconds, body))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _coerce_ts(value) -> float | None:
    """Best-effort coercion of a timestamp to unix-seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Heuristic: > 10^12 means it's milliseconds.
        return float(value) / 1000.0 if value > 1e12 else float(value)
    if isinstance(value, str):
        # Try ISO 8601 first.
        try:
            from datetime import datetime

            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            return None
    return None
