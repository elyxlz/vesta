"""The daemon's in-memory state and the mode-to-engine route table it serves.

Split out from `serve.py` so a later module (`doctor.py`) can read both without importing the
socket server. `serve.py` is the one importer that also runs the server.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import typing as tp

from . import camoufox, chromium
from . import protocol as p
from . import sessions as sessions_mod
from .display import display_readiness
from .handover_state import Handover
from .runtime_paths import Paths
from .runtimes import ExecOutcome


@dataclasses.dataclass
class State:
    paths: Paths
    table: sessions_mod.SessionTable
    inflight: dict[str, asyncio.Task[ExecOutcome]] = dataclasses.field(default_factory=dict)
    tasks: set[asyncio.Task[object]] = dataclasses.field(default_factory=set)
    display_lock: asyncio.Lock = dataclasses.field(default_factory=asyncio.Lock)
    handover: Handover | None = None
    last_error: p.Error | None = None
    asked_to_stop: bool = False


def own(state: State, coro: tp.Coroutine[None, None, object]) -> asyncio.Task[object]:
    """Every background task the daemon spawns is held here, so shutdown cancels and awaits it."""
    task = asyncio.create_task(coro)
    state.tasks.add(task)
    task.add_done_callback(state.tasks.discard)
    return task


ENGINES = {"chromium": chromium, "camoufox": camoufox}


def identity(paths: Paths) -> dict[str, p.JsonValue]:
    """Which daemon answered: its pid, the protocol it speaks, and the socket it serves."""
    return {"pid": os.getpid(), "protocol_version": p.PROTOCOL_VERSION, "socket": str(paths.socket)}


def routes(paths: Paths) -> dict[str, p.JsonValue]:
    """The mode-to-engine table, each route ready only with its binaries present and the display up."""
    display = display_readiness()
    display_ok = display["ready"] is True
    ready = {engine: not module.missing(paths) and display_ok for engine, module in ENGINES.items()}
    table: dict[str, p.JsonValue] = {}
    for mode, engine in p.ENGINE_FOR_MODE.items():
        table[mode] = {
            "engine": engine,
            "protocol": p.PROTOCOL_FOR_ENGINE[engine],
            "backend": "local",
            "ready": ready[engine],
            "api": {"portable": p.PORTABLE_API, "extensions": list(p.EXTENSIONS_FOR_ENGINE[engine])},
        }
    return {
        "default_mode": "standard",
        "routes": table,
        "portable_helpers": list(p.PORTABLE_HELPERS),
        "profiles_shared_between_engines": False,
        "display": display,
    }
