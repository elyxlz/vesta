"""Thin async wrappers over the tmux CLI.

Each ClaudeSDKClient owns a private tmux server (its own -L socket) so it is fully
isolated from any interactive tmux the user might be running and inherits the
agent process environment.
"""

import asyncio
import random

_TMUX = "tmux"
_BRACKETED_PASTE_START = "\x1b[200~"
_BRACKETED_PASTE_END = "\x1b[201~"
_SHORT_TEXT_CHARS = 240
_LONG_TEXT_CHARS = 1000
_PASTE_TEXT_CHARS = 1000
_TYPE_SHORT_CHUNK_MIN = 8
_TYPE_SHORT_CHUNK_MAX = 32
_TYPE_MEDIUM_CHUNK_MIN = 32
_TYPE_MEDIUM_CHUNK_MAX = 96
_TYPE_LONG_CHUNK_MIN = 96
_TYPE_LONG_CHUNK_MAX = 256
_TYPE_DELAY_MIN_S = 0.0005
_TYPE_DELAY_MAX_S = 0.003
_TYPE_PUNCTUATION_DELAY_MAX_S = 0.008
_SUBMIT_DELAY_MIN_S = 0.015
_SUBMIT_DELAY_MAX_S = 0.055
_DOUBLE_ESCAPE_DELAY_MIN_S = 0.015
_DOUBLE_ESCAPE_DELAY_MAX_S = 0.045
_TYPE_PAUSE_AFTER = frozenset(".!?,;:\n")


async def _run(socket: str, *args: str, stdin: bytes | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        _TMUX,
        "-L",
        socket,
        *args,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(input=stdin)
    rc = proc.returncode if proc.returncode is not None else -1
    return rc, out.decode(errors="replace"), err.decode(errors="replace")


async def start_session(socket: str, name: str, *, cwd: str, command: str, width: int = 220, height: int = 50) -> None:
    rc, _, err = await _run(socket, "new-session", "-d", "-s", name, "-x", str(width), "-y", str(height), "-c", cwd, "sh", "-c", command)
    if rc != 0:
        raise RuntimeError(f"tmux new-session failed: {err.strip()}")


async def send_keys(socket: str, name: str, *keys: str) -> None:
    await _run(socket, "send-keys", "-t", name, *keys)


async def send_literal(socket: str, name: str, text: str) -> None:
    await _run(socket, "send-keys", "-t", name, "-l", "--", text)


def _chunk_bounds(text_len: int) -> tuple[int, int]:
    if text_len > _LONG_TEXT_CHARS:
        return _TYPE_LONG_CHUNK_MIN, _TYPE_LONG_CHUNK_MAX
    if text_len > _SHORT_TEXT_CHARS:
        return _TYPE_MEDIUM_CHUNK_MIN, _TYPE_MEDIUM_CHUNK_MAX
    return _TYPE_SHORT_CHUNK_MIN, _TYPE_SHORT_CHUNK_MAX


async def type_text(socket: str, name: str, text: str) -> None:
    """Type `text` into the pane in randomized literal bursts without submitting."""
    await send_literal(socket, name, _BRACKETED_PASTE_START)
    index = 0
    chunk_min, chunk_max = _chunk_bounds(len(text))
    while index < len(text):
        remaining = len(text) - index
        chunk_len = random.randint(min(chunk_min, remaining), min(chunk_max, remaining))
        chunk = text[index : index + chunk_len]
        await send_literal(socket, name, chunk)
        index += chunk_len
        if index < len(text):
            delay = random.uniform(_TYPE_DELAY_MIN_S, _TYPE_DELAY_MAX_S)
            if chunk[-1] in _TYPE_PAUSE_AFTER:
                delay += random.uniform(0.0, _TYPE_PUNCTUATION_DELAY_MAX_S)
            await asyncio.sleep(delay)
    await send_literal(socket, name, _BRACKETED_PASTE_END)


async def submit_text(socket: str, name: str, text: str) -> None:
    if len(text) > _PASTE_TEXT_CHARS:
        await paste_text(socket, name, text)
    else:
        await type_text(socket, name, text)
    await asyncio.sleep(random.uniform(_SUBMIT_DELAY_MIN_S, _SUBMIT_DELAY_MAX_S))
    await send_keys(socket, name, "Enter")


async def send_double_escape(socket: str, name: str) -> None:
    await send_keys(socket, name, "Escape")
    await asyncio.sleep(random.uniform(_DOUBLE_ESCAPE_DELAY_MIN_S, _DOUBLE_ESCAPE_DELAY_MAX_S))
    await send_keys(socket, name, "Escape")


async def paste_text(socket: str, name: str, text: str) -> None:
    """Bracketed-paste `text` into the pane without submitting; newlines stay in the box."""
    await _run(socket, "load-buffer", "-b", "ccpaste", "-", stdin=text.encode())
    await _run(socket, "paste-buffer", "-t", name, "-b", "ccpaste", "-p", "-d")


async def capture_pane(socket: str, name: str) -> str:
    _, out, _ = await _run(socket, "capture-pane", "-t", name, "-p")
    return out


async def has_session(socket: str, name: str) -> bool:
    rc, _, _ = await _run(socket, "has-session", "-t", name)
    return rc == 0


async def kill_server(socket: str) -> None:
    await _run(socket, "kill-server")
