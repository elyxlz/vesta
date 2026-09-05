"""The in-process daemon the suites drive, and the deadline polls they wait on: no fixed sleeps."""

import asyncio
import os
import time

import pytest
from vesta_browser import serve

POLL_DEADLINE_SECS = 5.0
POLL_INTERVAL_SECS = 0.02
SOCKET_WAIT_POLLS = 100


def with_daemon(paths, coro_fn):
    """Runs `coro_fn` against a daemon serving `paths`, torn down through its own shutdown path."""

    async def run():
        server = asyncio.create_task(serve.serve(paths))
        for _ in range(SOCKET_WAIT_POLLS):
            if paths.socket.exists():
                break
            await asyncio.sleep(POLL_INTERVAL_SECS)
        try:
            return await coro_fn()
        finally:
            server.cancel()
            with pytest.raises(asyncio.CancelledError):
                await server

    return asyncio.run(run())


async def wait_for_state(paths, name, wanted, timeout=POLL_DEADLINE_SECS):
    """Polls `sessions` until `name` reads `wanted`."""
    deadline = time.monotonic() + timeout
    states = {}
    while time.monotonic() < deadline:
        listing = await serve.request(paths, {"version": 1, "op": "sessions", "request_id": "poll"})
        states = {s["name"]: s["state"] for s in listing["data"]["sessions"]}
        if name in states and states[name] == wanted:
            return
        await asyncio.sleep(POLL_INTERVAL_SECS)
    raise AssertionError(f"session {name!r} never reached state {wanted!r}; last saw {states}")


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def wait_until_dead(pid, timeout=POLL_DEADLINE_SECS):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        await asyncio.sleep(POLL_INTERVAL_SECS)
    return False


async def wait_until_all_dead(pids, timeout=POLL_DEADLINE_SECS):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(pid_alive(pid) for pid in pids):
            return True
        await asyncio.sleep(POLL_INTERVAL_SECS)
    return not any(pid_alive(pid) for pid in pids)
