"""Playback state: a pure function of the `speak` frames and the playback reports.

The client queues the plays and plays them in arrival order, and it reports what its speaker
did. The engine derives the rest from those reports: when the agent is speaking, what the agent
is saying, and which plays a stop cut or dropped.
"""

import dataclasses as dc
import typing as tp


@dc.dataclass(frozen=True)
class Play:
    id: str
    text: str
    # The engine's own name for this play of this session: two sessions can speak the same id.
    token: str
    # The first sample reached the speaker.
    started: bool = False
    # The play finished or failed.
    over: bool = False


@dc.dataclass(frozen=True)
class PlaybackState:
    # Plays sent to the client, in order, up to the last one that is not over.
    sent: tuple[Play, ...] = ()
    # Plays that wait for the end of the user's turn.
    held: tuple[Play, ...] = ()


class Stop(tp.NamedTuple):
    state: PlaybackState
    # The play that was cut: it started and was not over.
    cut: Play | None
    # Every sent play with no `started` report, including plays whose bytes the client has.
    dropped: tuple[Play, ...]


def speak(state: PlaybackState, play: Play, *, hold: bool) -> tuple[PlaybackState, tuple[Play, ...]]:
    """Take a new play. Returns the plays to send now: none while the user holds the floor."""
    if hold:
        return dc.replace(state, held=(*state.held, play)), ()
    return dc.replace(state, sent=(*state.sent, play)), (play,)


def release(state: PlaybackState) -> tuple[PlaybackState, tuple[Play, ...]]:
    """The user's turn is over: the held plays go out, in `speak` order."""
    return PlaybackState(sent=(*state.sent, *state.held)), state.held


def report(state: PlaybackState, play_id: str, status: tp.Literal["started", "finished", "failed"]) -> PlaybackState:
    """Apply one report to the oldest play with that id that is not over."""
    target = next((play for play in state.sent if play.id == play_id and not play.over), None)
    if target is None:
        return state
    updated = dc.replace(target, started=True) if status == "started" else dc.replace(target, over=True)
    sent = tuple(updated if play is target else play for play in state.sent)
    # Once every sent play is over, nothing of them matters to a later stop.
    return dc.replace(state, sent=() if all(play.over for play in sent) else sent)


def drop_held(state: PlaybackState, token: str) -> PlaybackState:
    """Forget a held play whose synthesis failed: it never reaches the client."""
    return dc.replace(state, held=tuple(play for play in state.held if play.token != token))


def speaking(state: PlaybackState) -> bool:
    """A play has started, and not every sent play is over."""
    return any(play.started for play in state.sent)


def saying(state: PlaybackState) -> Play | None:
    """The play that runs now."""
    return next((play for play in state.sent if play.started and not play.over), None)


def stop(state: PlaybackState) -> Stop:
    """Stop the audio and clear the client's queue. Held plays stay: they are not at the client."""
    return Stop(
        state=dc.replace(state, sent=()),
        cut=saying(state),
        dropped=tuple(play for play in state.sent if not play.started),
    )
