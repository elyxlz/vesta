"""The session table: one browser process and one profile per name, engine pinned for life.

A session is known while its profile directory exists, so the table survives a daemon restart as a
set of `stopped` sessions. Engine-specific process handles hang off `Session.runtime`.
"""

from __future__ import annotations

import dataclasses
import pathlib as pl
import time
import typing as tp

from . import protocol as p
from .runtime_paths import Paths
from .runtimes import EngineRuntime

MODE_FOR_ENGINE: dict[p.Engine, p.Mode] = {engine: mode for mode, engine in p.ENGINE_FOR_MODE.items()}


@dataclasses.dataclass
class Session:
    name: str
    mode: p.Mode
    engine: p.Engine
    state: p.SessionState
    profile_dir: pl.Path
    scratch_dir: pl.Path
    artifact_dir: pl.Path
    last_activity: float
    runtime: EngineRuntime | None = None
    request_id: str | None = None


@dataclasses.dataclass
class SessionTable:
    paths: Paths
    sessions: dict[str, Session]
    clock: tp.Callable[[], float]


def _make(paths: Paths, name: str, engine: p.Engine, now: float) -> Session:
    session = Session(
        name=name,
        mode=MODE_FOR_ENGINE[engine],
        engine=engine,
        state="stopped",
        profile_dir=paths.profiles / engine / name,
        scratch_dir=paths.sessions / name,
        artifact_dir=paths.artifacts / name,
        last_activity=now,
    )
    for directory in (session.profile_dir, session.scratch_dir, session.artifact_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return session


def load_table(paths: Paths, clock: tp.Callable[[], float] = time.monotonic) -> SessionTable:
    table = SessionTable(paths=paths, sessions={}, clock=clock)
    for engine in p.ENGINE_FOR_MODE.values():
        engine_dir = paths.profiles / engine
        if not engine_dir.is_dir():
            continue
        for profile in sorted(engine_dir.iterdir()):
            if profile.is_dir() and p.SESSION_NAME_RE.match(profile.name):
                table.sessions[profile.name] = _make(paths, profile.name, engine, clock())
    return table


def resolve_session(table: SessionTable, name: str, mode: p.Mode | None) -> Session:
    if not p.SESSION_NAME_RE.match(name):
        raise p.BrowserError(
            p.error(
                "invalid_request",
                "validation",
                f"session name {name!r} must match {p.SESSION_NAME_RE.pattern}",
                retryable=False,
                suggested_action="use lowercase letters, digits, '-' and '_'",
            )
        )
    if name in table.sessions:
        session = table.sessions[name]
        if mode is not None and mode != session.mode:
            raise p.BrowserError(
                p.error(
                    "session_engine_conflict",
                    "routing",
                    f"session {name!r} is pinned to {session.engine} ({session.mode}); requested {mode}",
                    retryable=False,
                    suggested_action="omit the mode to reuse this session, or start a new session name for the other engine",
                )
            )
        return session
    session = _make(table.paths, name, p.ENGINE_FOR_MODE[mode or "standard"], table.clock())
    table.sessions[name] = session
    return session


def touch(table: SessionTable, session: Session) -> None:
    session.last_activity = table.clock()


def mark(session: Session, state: p.SessionState) -> None:
    session.state = state


def idle_sessions(table: SessionTable, idle_secs: int = p.SESSION_IDLE_STOP_SECS) -> list[Session]:
    cutoff = table.clock() - idle_secs
    return [x for x in table.sessions.values() if x.state == "ready" and x.last_activity < cutoff]


def info(session: Session) -> p.SessionInfo:
    return p.session_info(session.name, session.mode, session.engine, session.state)
