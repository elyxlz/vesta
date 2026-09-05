"""The live handover's record and the one payload every handover op answers with.

Below `daemon_state.py`, which carries the record, and below `handover.py`, which fills it: a
handover is one at a time, so the daemon holds at most one of these.
"""

from __future__ import annotations

import asyncio
import dataclasses
import typing as tp

from . import protocol as p
from .display import DisplayStack
from .sessions import Session

HandoverState = tp.Literal["starting", "live", "stopping", "expired", "failed", "inactive"]
StopReason = tp.Literal["stopped", "expired", "failed"]


@dataclasses.dataclass
class Handover:
    """One handover, filled in as it comes up: the stack and the key exist only once they are made.

    `user_url` is the only place the minted secret lives, so nothing else can log it.
    """

    id: str
    session: Session
    key_label: str
    expires_at: str
    state: HandoverState
    stack: DisplayStack | None = None
    key_id: str | None = None
    user_url: str = ""
    task: asyncio.Task[None] | None = None


def payload(handover: Handover | None) -> dict[str, p.JsonValue]:
    """What `handover start|status|stop` answers with; every field is null while none is live."""
    if handover is None or handover.state == "inactive":
        return {"state": "inactive", "handover_id": None, "session": None, "engine": None, "user_url": None, "expires_at": None}
    return {
        "state": handover.state,
        "handover_id": handover.id,
        "session": handover.session.name,
        "engine": handover.session.engine,
        "user_url": handover.user_url,
        "expires_at": handover.expires_at,
    }
