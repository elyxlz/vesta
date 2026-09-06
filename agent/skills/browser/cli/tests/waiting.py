"""The in-process daemon the suites drive, and the deadline polls they wait on: no fixed sleeps."""

import asyncio
import json
import os
import pathlib as pl
import time
import urllib.request

import pytest
from vesta_browser import protocol as p
from vesta_browser import serve

POLL_DEADLINE_SECS = 5.0
POLL_INTERVAL_SECS = 0.02
HTTP_TIMEOUT_SECS = 5


async def wait_for_socket(paths, timeout=POLL_DEADLINE_SECS):
    """Polls until the daemon's socket exists."""
    await wait_for_file(paths.socket, timeout)


def with_daemon(paths, coro_fn):
    """Runs `coro_fn` against a daemon serving `paths`, torn down through its own shutdown path."""

    async def run():
        server = asyncio.create_task(serve.serve(paths))
        await wait_for_socket(paths)
        try:
            return await coro_fn()
        finally:
            server.cancel()
            with pytest.raises(asyncio.CancelledError):
                await server

    return asyncio.run(run())


async def request(paths, payload):
    """One request to the in-process daemon, on the test's own loop so the server keeps running."""
    reader, writer = await asyncio.open_unix_connection(str(paths.socket), limit=p.REQUEST_MAX_BYTES * 4)
    writer.write((json.dumps(payload) + "\n").encode())
    await writer.drain()
    line = await reader.readline()
    writer.close()
    return json.loads(line)


def exec_request(session, code, *, mode=None, timeout_s=10, request_id="r1"):
    return p.request("exec", request_id, session=session, mode=mode, timeout_s=timeout_s, code=code)


async def wait_for_state(paths, name, wanted, timeout=POLL_DEADLINE_SECS):
    """Polls `sessions` until `name` reads `wanted`."""
    deadline = time.monotonic() + timeout
    states = {}
    while time.monotonic() < deadline:
        listing = await request(paths, p.request("sessions", "poll"))
        states = {s["name"]: s["state"] for s in listing["data"]["sessions"]}
        if name in states and states[name] == wanted:
            return
        await asyncio.sleep(POLL_INTERVAL_SECS)
    raise AssertionError(f"session {name!r} never reached state {wanted!r}; last saw {states}")


async def wait_for_file(path, timeout=POLL_DEADLINE_SECS):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        await asyncio.sleep(POLL_INTERVAL_SECS)
    raise AssertionError(f"{path} was never created")


async def wait_for_recorded_pids(pids_file, wanted, timeout=POLL_DEADLINE_SECS):
    """Polls the display fakes' pid record until it names at least `wanted` processes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pids_file.exists() and len(pids_file.read_text().split()) >= wanted:
            return
        await asyncio.sleep(POLL_INTERVAL_SECS)
    raise AssertionError(f"{pids_file} never recorded {wanted} pids")


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def cmdline_of(pid):
    return pl.Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")


def fetch(url):
    """One GET: the status and the body."""
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SECS) as answer:
        return answer.status, answer.read().decode()


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
