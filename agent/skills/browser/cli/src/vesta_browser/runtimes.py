"""Engine process handles and the per-exec outcome, shared by the session table and both engine supervisors."""

from __future__ import annotations

import asyncio
import dataclasses
import pathlib as pl

from . import protocol as p


@dataclasses.dataclass
class ChromiumRuntime:
    process: asyncio.subprocess.Process
    port: int


@dataclasses.dataclass
class CamoufoxRuntime:
    process: asyncio.subprocess.Process
    config_path: pl.Path
    last_page: p.PageInfo


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
    warnings: list[str] = dataclasses.field(default_factory=list)
