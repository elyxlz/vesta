"""The daemon's in-memory state and the mode-to-engine route table it serves.

Split out from `serve.py` so a later module (`doctor.py`) can read both without importing the
socket server. `serve.py` is the one importer that also runs the server.
"""

from __future__ import annotations

import asyncio
import dataclasses

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
    tasks: set[asyncio.Task[None]] = dataclasses.field(default_factory=set)
    restart_pending: set[str] = dataclasses.field(default_factory=set)
    handover: Handover | None = None
    last_error: p.Error | None = None
    asked_to_stop: bool = False


def routes(paths: Paths) -> dict[str, p.JsonValue]:
    """The mode-to-engine table, each route ready only with its binaries present and the display up."""
    display = display_readiness(paths)
    display_ok = display["ready"] is True
    ready = {
        "chromium": paths.chromium_exe.is_file() and paths.browser_use_bin.is_file() and display_ok,
        "camoufox": paths.camoufox_python.is_file() and paths.camoufox_exe.is_file() and paths.worker_script.is_file() and display_ok,
    }
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
