"""Starting and stopping a session's engine: the one owner of both decisions.

Below `serve.py` and `handover.py` because both drive the same session runtimes: an exec starts one
and a handover replaces it with a headed one, and neither may hold its own rule for when a runtime
may be torn out.
"""

from __future__ import annotations

from . import camoufox, chromium
from . import sessions as sessions_mod
from .daemon_state import State

ENGINES = {"chromium": chromium, "camoufox": camoufox}


async def _ensure_running(state: State, session: sessions_mod.Session) -> list[str]:
    """Starts the session's engine when it is not running. Returns warnings (worker_restarted after a kill)."""
    if session.runtime is not None:
        return []
    restarted = session.state == "stopped" and session.name in state.restart_pending
    state.restart_pending.discard(session.name)
    sessions_mod.mark(session, "starting")
    try:
        session.runtime = await ENGINES[session.engine].start(session, state.paths)
    except Exception:
        # Any failure at all, not only a named one: a session left `starting` refuses every later
        # exec and no command can bring it back.
        sessions_mod.mark(session, "stopped")
        session.runtime = None
        raise
    sessions_mod.mark(session, "ready")
    return ["worker_restarted"] if restarted else []


async def _stop_session(session: sessions_mod.Session, *, force: bool = False) -> bool:
    """Stops a session's runtime. The one owner of the decision: refuses (returns False) a busy,
    starting, or handed-over session unless `force`, so a stop path never tears a runtime out from
    under an exec or out of the user's own hands.
    """
    if not force and session.state in ("busy", "starting", "handed_over"):
        return False
    runtime = session.runtime
    session.runtime = None
    # Marked before the engine stop is awaited, so an exec arriving during the teardown sees a
    # stopped session and starts a runtime of its own that this trailing write cannot undo.
    sessions_mod.mark(session, "stopped")
    if runtime is not None:
        await ENGINES[session.engine].stop(runtime, session)
    return True
