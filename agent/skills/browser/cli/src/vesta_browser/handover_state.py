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
    """One handover, filled in as it comes up: the stack, the key, and the URL exist only once they
    are made, and `task` holds whatever the daemon currently owns for this handover, the start
    while it is `starting` and the expiry timer once it is `live`.

    `user_url` is the only place the minted secret lives, so nothing else can log it, and the
    teardown clears it: a revoked key must not keep printing as a link.
    """

    id: str
    session: Session
    key_label: str
    state: HandoverState
    stack: DisplayStack | None = None
    key_id: str | None = None
    user_url: str = ""
    expires_at: str = ""
    task: asyncio.Task[None] | None = None


def diagnostic(handover: Handover | None) -> dict[str, p.JsonValue]:
    """The handover's shape, with no URL in it: what a report the agent prints may carry.

    The keyed URL is added by `payload` alone, so a field added here can never carry the secret.
    """
    if handover is None or handover.state == "inactive":
        return {"state": "inactive", "handover_id": None, "session": None, "engine": None, "expires_at": None}
    return {
        "state": handover.state,
        "handover_id": handover.id,
        "session": handover.session.name,
        "engine": handover.session.engine,
        "expires_at": handover.expires_at or None,
    }


def payload(handover: Handover | None) -> dict[str, p.JsonValue]:
    """What `handover start|status|stop` answers with; a field it has no answer for yet is null."""
    user_url = handover.user_url if handover is not None and handover.state != "inactive" else ""
    return {**diagnostic(handover), "user_url": user_url or None}
