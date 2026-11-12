"""Per-stage latency of a voice turn, as INFO log lines.

Each line reads `timing turn=<id> stage=<stage> ms=<n>`, where `ms` counts from the end of the
user's speech: the `end_turn` commit, or the STT provider's own commit when the client sent none.
A play that no turn started (the agent speaks first) gets its own clock at `speak`.
"""

import dataclasses as dc
import logging
import secrets
import time

logger = logging.getLogger("voice.timing")

TURN_ID_BYTES = 3


@dc.dataclass(frozen=True)
class TurnClock:
    id: str
    start: float


def enable() -> None:
    """Send the timing lines to stderr (the daemon's log). The service configures no other
    logging, so the root logger would drop INFO."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def start() -> TurnClock:
    return TurnClock(secrets.token_hex(TURN_ID_BYTES), time.monotonic())


def mark(clock: TurnClock | None, stage: str, detail: str = "") -> None:
    if clock is None:
        return
    ms = (time.monotonic() - clock.start) * 1000
    logger.info("timing turn=%s stage=%s ms=%.0f%s", clock.id, stage, ms, f" {detail}" if detail else "")
