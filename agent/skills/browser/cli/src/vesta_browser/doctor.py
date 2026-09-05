"""One report of everything the daemon knows: binaries, versions, sessions, artifacts, the handover, and the last error.

The handover block is read from the record alone. Reading it through `handover.status` would give
a report the power to fail a live handover and schedule its teardown, and would put the keyed URL
in a report the agent prints.
"""

from __future__ import annotations

import asyncio
import pathlib as pl

from . import display, handover_state
from . import protocol as p
from . import sessions as sessions_mod
from .daemon_state import State, identity, routes
from .procs import run_capture
from .runtime_paths import Paths

VERSION_PROBE_TIMEOUT_SECS = 10


async def _probe(argv: list[str]) -> str:
    try:
        code, out, _ = await run_capture(argv, VERSION_PROBE_TIMEOUT_SECS)
    except OSError:
        return "unavailable"
    return out if code == 0 and out else "unavailable"


def _two(text: str) -> tuple[str, str]:
    if text == "unavailable":
        return "unavailable", "unavailable"
    fields = [*text.split(), "unavailable", "unavailable"][:2]
    return fields[0], fields[1]


def _versions_program(names: list[str]) -> str:
    return f"import importlib.metadata as m; print(' '.join(m.version(n) for n in {names!r}))"


async def versions(paths: Paths) -> dict[str, p.JsonValue]:
    chromium, standard, stealth = await asyncio.gather(
        _probe([str(paths.chromium_exe), "--version"]),
        _probe([str(paths.browser_use_bin.parent / "python"), "-c", _versions_program(["browser-use", "browser-harness"])]),
        _probe([str(paths.camoufox_python), "-c", _versions_program(["camoufox", "playwright"])]),
    )
    browser_use, browser_harness = _two(standard)
    camoufox, playwright = _two(stealth)
    return {
        "chromium": chromium,
        "browser-use": browser_use,
        "browser-harness": browser_harness,
        "camoufox": camoufox,
        "playwright": playwright,
        "camoufox_browser": paths.camoufox_exe.parent.name,
    }


def _tree_bytes(root: pl.Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file()) if root.is_dir() else 0


async def report(state: State) -> dict[str, p.JsonValue]:
    paths = state.paths
    return {
        "daemon": {**identity(paths), "log": str(paths.log)},
        "engines": {**routes(paths), "versions": await versions(paths)},
        "sessions": sessions_mod.listing(state.table),
        "artifacts": {"root": str(paths.artifacts), "bytes": await asyncio.to_thread(_tree_bytes, paths.artifacts)},
        "handover": {**display.stream_readiness(paths), **handover_state.diagnostic(state.handover)},
        "last_error": dict(state.last_error) if state.last_error is not None else None,
    }


async def op_doctor(state: State, request_id: str, _request: dict[str, p.JsonValue]) -> p.Result:
    return p.result(request_id=request_id, op="doctor", ok=True, data=await report(state))
