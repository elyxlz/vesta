"""The spoken-reply clause of a reply hint, asked from the voice service.

The voice skill owns what its voice does with the text of a reply, so this service asks it and
adds the answer to the hint as it is. With no voice daemon, or one that does not answer in time,
the hint has no such clause.
"""

import asyncio
import pathlib as pl

import aiohttp

# The voice daemon is on this box, so an answer takes a few milliseconds. The limit only keeps a
# daemon that hangs from holding a message.
VOICE_TIMEOUT_SECS = 0.3


def voice_http() -> aiohttp.ClientSession:
    """The session the service keeps open to ask the voice daemon."""
    return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=VOICE_TIMEOUT_SECS))


def _voice_port(port_file: pl.Path) -> int | None:
    try:
        return int(port_file.read_text())
    except (OSError, ValueError):
        return None


async def spoken_reply_hint(http: aiohttp.ClientSession, voice_port_file: pl.Path) -> str:
    """What the agent must know to write a reply that the voice can speak, or empty text."""
    port = await asyncio.to_thread(_voice_port, voice_port_file)
    if port is None:
        return ""
    try:
        async with http.get(f"http://127.0.0.1:{port}/tts/reply-hint") as resp:
            if resp.status != 200:
                return ""
            body = await resp.json()
    except (TimeoutError, aiohttp.ClientError, ValueError):
        return ""
    hint = body["reply_hint"] if isinstance(body, dict) and "reply_hint" in body else ""
    return hint if isinstance(hint, str) else ""
