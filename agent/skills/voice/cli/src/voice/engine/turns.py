"""Turn decisions: a pure function of the state, one event, and the clock.

The STT provider decides the end of a turn. This module decides the rest: when a turn that is
said to the agent starts, which committed text goes to the agent, and what live text does to a
reply that plays (pause, resume, or stop).

A verdict of None means "no verdict": the judge is off, or it had no answer. Text with no
verdict counts as said to the agent, and the two time rules decide a barge-in: a segment that
commits before HOLD_WAIT_MS was a backchannel, and one that is still open after it takes the floor.
"""

import dataclasses as dc
import typing as tp

from voice.providers.base import Verdict

from . import frames

# A backchannel of half a second commits about 0.5 s to 0.8 s after the pause, so this lets it
# pass, and speech that continues for a second after the pause takes the floor.
HOLD_WAIT_MS = 1000

Phase = tp.Literal["idle", "user_turn", "paused"]


@dc.dataclass(frozen=True)
class TurnState:
    phase: Phase = "idle"
    # The clock time of `pause_playback`, while the phase is `paused`.
    paused_at: float | None = None
    # Live text of the open segment arrived.
    segment_seen: bool = False
    # The open segment already got its `ignored`, so its commit sends nothing.
    segment_settled: bool = False


class Live(tp.TypedDict):
    kind: tp.Literal["live"]
    text: str


class Judged(tp.TypedDict):
    kind: tp.Literal["judged"]
    text: str
    verdict: Verdict | None


class Committed(tp.TypedDict):
    kind: tp.Literal["committed"]
    text: str
    verdict: Verdict | None


class Tick(tp.TypedDict):
    kind: tp.Literal["tick"]


class StoppedByUser(tp.TypedDict):
    kind: tp.Literal["stopped_by_user"]


TurnEvent = Live | Judged | Committed | Tick | StoppedByUser


class StopNow(tp.TypedDict):
    """Stop the playback. The session completes it into a `stop_playback` frame, because the cut
    play and the dropped plays are playback state."""

    type: tp.Literal["stop_now"]


Action = frames.TurnStart | frames.TurnEnd | frames.TurnDropped | frames.Ignored | frames.PausePlayback | frames.ResumePlayback | StopNow

TURN_START: frames.TurnStart = {"type": "turn_start"}
PAUSE: frames.PausePlayback = {"type": "pause_playback"}
RESUME: frames.ResumePlayback = {"type": "resume_playback"}
STOP: StopNow = {"type": "stop_now"}


def wire_state(state: TurnState, speaking: bool) -> frames.StateValue:
    if state.phase == "user_turn":
        return "user_turn"
    if state.phase == "paused":
        return "agent_paused"
    return "agent_speaking" if speaking else "listening"


def _to_agent(verdict: Verdict | None) -> bool:
    return verdict is None or verdict["said_to"] == "agent"


def _takes_floor(verdict: Verdict) -> bool:
    """Said to the agent while a reply plays, and not a backchannel."""
    return verdict["said_to"] == "agent" and verdict["wants_stop"] is not False


def _ignored(text: str, verdict: Verdict | None) -> frames.Ignored:
    if verdict is None or verdict["said_to"] == "agent":
        return {"type": "ignored", "text": text, "kind": "backchannel"}
    return {"type": "ignored", "text": text, "kind": verdict["said_to"]}


def _on_live(state: TurnState, *, can_pause: bool, now: float) -> tuple[TurnState, list[Action]]:
    first = not state.segment_seen
    seen = dc.replace(state, segment_seen=True)
    if state.phase == "idle" and can_pause and first:
        return dc.replace(seen, phase="paused", paused_at=now), [PAUSE]
    return seen, []


def _on_judged(state: TurnState, event: Judged, *, can_pause: bool) -> tuple[TurnState, list[Action]]:
    verdict = event["verdict"]
    takes_floor = verdict is not None and _takes_floor(verdict)
    if state.phase == "paused" and verdict is not None:
        if takes_floor:
            return dc.replace(state, phase="user_turn", paused_at=None), [STOP, TURN_START]
        return dc.replace(state, phase="idle", paused_at=None, segment_settled=True), [RESUME, _ignored(event["text"], verdict)]
    # While a reply plays and this segment did not pause it (it began before the reply, or it
    # was already answered with a resume), only a clear verdict takes the floor.
    if state.phase == "idle" and (takes_floor if can_pause else _to_agent(verdict)):
        return dc.replace(state, phase="user_turn"), [STOP, TURN_START] if can_pause else [TURN_START]
    return state, []


def _committed_while_playing(text: str, verdict: Verdict | None, *, resume: bool) -> list[Action]:
    """A segment that ended while a reply played (paused when `resume` is true)."""
    if verdict is not None and _takes_floor(verdict):
        return [STOP, TURN_START, {"type": "turn_end", "text": text}]
    ignored: list[Action] = [_ignored(text, verdict)] if text else []
    return [RESUME, *ignored] if resume else ignored


def _on_committed(state: TurnState, event: Committed, *, can_pause: bool) -> tuple[TurnState, list[Action]]:
    text, verdict = event["text"], event["verdict"]
    actions: list[Action]
    if state.phase == "user_turn":
        if not text:
            actions = [{"type": "turn_dropped", "text": "", "kind": None}]
        elif _to_agent(verdict):
            actions = [{"type": "turn_end", "text": text}]
        else:
            actions = [{"type": "turn_dropped", "text": text, "kind": _ignored(text, verdict)["kind"]}]
    elif state.phase == "paused":
        actions = _committed_while_playing(text, verdict, resume=True)
    elif state.segment_settled or not text:
        actions = []
    elif can_pause:
        actions = _committed_while_playing(text, verdict, resume=False)
    elif _to_agent(verdict):
        actions = [TURN_START, {"type": "turn_end", "text": text}]
    else:
        actions = [_ignored(text, verdict)]
    return TurnState(), actions


def _on_tick(state: TurnState, *, now: float) -> tuple[TurnState, list[Action]]:
    if state.phase == "paused" and state.paused_at is not None and (now - state.paused_at) * 1000 >= HOLD_WAIT_MS:
        return dc.replace(state, phase="user_turn", paused_at=None), [STOP, TURN_START]
    return state, []


def _on_stopped_by_user(state: TurnState) -> tuple[TurnState, list[Action]]:
    if state.phase == "paused":
        return dc.replace(state, phase="idle", paused_at=None), [STOP]
    return state, [STOP]


def step(state: TurnState, event: TurnEvent, *, speaking: bool, barge_in: bool, now: float) -> tuple[TurnState, list[Action]]:
    """The next state, and the actions to send in order.

    `speaking` is the playback state (a reply plays or is paused), `barge_in` is the session's
    barge-in result, and `now` is a monotonic clock in seconds.
    """
    can_pause = speaking and barge_in
    if event["kind"] == "live":
        return _on_live(state, can_pause=can_pause, now=now)
    if event["kind"] == "judged":
        return _on_judged(state, event, can_pause=can_pause)
    if event["kind"] == "committed":
        return _on_committed(state, event, can_pause=can_pause)
    if event["kind"] == "tick":
        return _on_tick(state, now=now)
    return _on_stopped_by_user(state)
