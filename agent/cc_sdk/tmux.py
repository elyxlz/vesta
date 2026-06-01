"""Thin async wrappers over the tmux CLI.

Each ClaudeSDKClient owns a private tmux server (its own -L socket) so it is fully
isolated from any interactive tmux the user might be running and inherits the
agent process environment.
"""

import asyncio

_TMUX = "tmux"


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
    rc, _, err = await _run(
        socket, "new-session", "-d", "-s", name, "-x", str(width), "-y", str(height), "-c", cwd, "sh", "-c", command
    )
    if rc != 0:
        raise RuntimeError(f"tmux new-session failed: {err.strip()}")


async def send_keys(socket: str, name: str, *keys: str) -> None:
    await _run(socket, "send-keys", "-t", name, *keys)


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
