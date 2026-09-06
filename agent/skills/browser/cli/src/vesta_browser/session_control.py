"""Starting, stopping, and settling a session's engine: the one owner of all three decisions.

Below `serve.py` and `handover.py` because both drive the same session runtimes, so neither may
hold its own rule for when a runtime may be torn out or for what a session reads once its work ends.
"""

from __future__ import annotations

from . import display
from . import protocol as p
from . import sessions as sessions_mod
from .daemon_state import ENGINES, State
from .runtime_paths import Paths
from .runtimes import HeadedDisplay


async def ensure_running(state: State, session: sessions_mod.Session) -> list[str]:
    """Starts the session's engine, headed on its own claimed display, when it is not running.
    Refuses a session another request holds, since a second start would claim a second display and
    browser for one session. Returns warnings (worker_restarted after a kill).
    """
    if session.state in ("busy", "starting"):
        raise p.BrowserError(p.invalid(f"session {session.name!r} is {session.state}; retry once the current request finishes"))
    if session.runtime is not None:
        return []
    restarted, session.restart_pending = session.restart_pending, False
    session.state = "starting"
    try:
        # One claim at a time across the daemon: sessions share one X socket dir, so two claims
        # running together pick the same free number and one of them ends up on the other's Xvfb.
        async with state.display_lock:
            session.display = await display.start_session_display(state.paths)
        headed = HeadedDisplay(session.display.display, display.SCREEN_W, display.SCREEN_H)
        session.runtime = await ENGINES[session.engine].start(session, state.paths, headed=headed)
    except BaseException as exc:
        # Any failure at all, not only a named one, and a cancellation too: a session left
        # `starting` refuses every later exec and no command can bring it back, and a claimed
        # display must not outlive the start it was claimed for.
        session.state = "stopped"
        session.runtime = None
        if session.display is not None:
            await display.stop_session_display(state.paths, session.display)
            session.display = None
        if isinstance(exc, display.DisplayError):
            raise p.BrowserError(p.unavailable(str(exc))) from exc
        raise
    session.state = "ready"
    return ["worker_restarted"] if restarted else []


async def stop_session(paths: Paths, session: sessions_mod.Session, *, force: bool = False) -> bool:
    """Stops a session's runtime and its own display. The one owner of the decision: refuses
    (returns False) a busy, starting, or handed-over session unless `force`, so a stop path never
    tears a runtime out from under an exec or out of the user's own hands.
    """
    if not force and session.state in ("busy", "starting", "handed_over"):
        return False
    runtime = session.runtime
    session.runtime = None
    # Marked before the engine stop is awaited, so an exec arriving during the teardown sees a
    # stopped session and starts a runtime of its own that this trailing write cannot undo.
    session.state = "stopped"
    try:
        if runtime is not None:
            await ENGINES[session.engine].stop(runtime, session)
    finally:
        session_display, session.display = session.display, None
        if session_display is not None:
            await display.stop_session_display(paths, session_display)
    return True


async def settle(state: State, session: sessions_mod.Session) -> None:
    """Gives a session back once its exec or handover ends: `ready` on the same runtime, or, for a
    runtime that died under that use, reaped with its display and queued for a restart so the next
    start brings a fresh browser and says it did."""
    if session.runtime is not None and session.runtime.process.returncode is None:
        session.state = "ready"
    else:
        await stop_session(state.paths, session, force=True)
        session.restart_pending = True
    sessions_mod.touch(state.table, session)
