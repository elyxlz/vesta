"""Engine process handles and the per-exec outcome, shared by the session table and both engine supervisors."""

from __future__ import annotations

import asyncio
import dataclasses
import time


@dataclasses.dataclass
class ChromiumRuntime:
    process: asyncio.subprocess.Process
    port: int


@dataclasses.dataclass
class CamoufoxRuntime:
    process: asyncio.subprocess.Process


EngineRuntime = ChromiumRuntime | CamoufoxRuntime


@dataclasses.dataclass(frozen=True)
class HeadedDisplay:
    """The X display and window size every engine launches onto: a session's own Xvfb."""

    display: str
    width: int
    height: int


@dataclasses.dataclass
class ExecOutcome:
    stdout: str
    stderr: str
    exit_code: int | None
    duration_ms: int
    timed_out: bool = False
    cancelled: bool = False
    capability_mismatch: str | None = None


def elapsed_ms(started: float) -> int:
    """Milliseconds since a `time.monotonic()` reading."""
    return int((time.monotonic() - started) * 1000)
