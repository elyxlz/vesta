"""The frames of the `/voice/session` socket: one TypedDict for each, and one parse function.

Each text frame is a JSON object with `type`, and its fields are flat beside it. A receiver
ignores a frame type and a field that it does not know. ~/agent/skills/voice/PROTOCOL.md is the
reference for a client.
"""

import json
import typing as tp

from voice.settings import JsonValue

# The one mic format the engine accepts.
MIC_AUDIO = {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1}

# Play format -> the Content-Type of its audio on the `/voice/play/<token>` route.
PLAY_FORMATS: dict[str, str] = {
    "mp3_22050": "audio/mpeg",
    "mp3_44100": "audio/mpeg",
    "pcm_16000": "audio/l16;rate=16000",
    "pcm_22050": "audio/l16;rate=22050",
    "pcm_24000": "audio/l16;rate=24000",
    "ulaw_8000": "audio/basic",
    "opus_48000": "audio/ogg",
}

Delivery = tp.Literal["url", "bytes"]
StateValue = tp.Literal["listening", "user_turn", "agent_speaking", "agent_paused"]
IgnoredKind = tp.Literal["backchannel", "echo", "other_person", "not_speech"]
PlaybackReportState = tp.Literal["started", "finished", "failed", "stopped_by_user"]
EndedReason = tp.Literal["client_ended", "stt_failed", "stt_limit", "not_configured", "unsupported_format"]

# --- client -> engine ---


class StartSession(tp.TypedDict):
    type: tp.Literal["start_session"]
    client: str
    mic_supported: bool
    delivery: Delivery
    formats: list[str]
    # False means that this session cannot do barge-in. None is an absent field.
    barge_in: bool | None


class Speak(tp.TypedDict):
    type: tp.Literal["speak"]
    id: str
    text: str


class PlaybackReport(tp.TypedDict):
    type: tp.Literal["playback"]
    id: str
    state: PlaybackReportState


class EndTurn(tp.TypedDict):
    type: tp.Literal["end_turn"]


class EndSession(tp.TypedDict):
    type: tp.Literal["end_session"]


ClientFrame = StartSession | Speak | PlaybackReport | EndTurn | EndSession

# --- engine -> client ---


class State(tp.TypedDict):
    type: tp.Literal["state"]
    value: StateValue


class Transcript(tp.TypedDict):
    type: tp.Literal["transcript"]
    text: str


class TurnStart(tp.TypedDict):
    type: tp.Literal["turn_start"]


class TurnEnd(tp.TypedDict):
    type: tp.Literal["turn_end"]
    text: str


class TurnDropped(tp.TypedDict):
    type: tp.Literal["turn_dropped"]
    text: str
    kind: IgnoredKind | None


class Ignored(tp.TypedDict):
    type: tp.Literal["ignored"]
    text: str
    kind: IgnoredKind


class Play(tp.TypedDict):
    type: tp.Literal["play"]
    id: str
    format: str
    # Present in `url` delivery only.
    url: tp.NotRequired[str]


class PlayDone(tp.TypedDict):
    type: tp.Literal["play_done"]
    id: str


class PausePlayback(tp.TypedDict):
    type: tp.Literal["pause_playback"]


class ResumePlayback(tp.TypedDict):
    type: tp.Literal["resume_playback"]


class StopPlayback(tp.TypedDict):
    type: tp.Literal["stop_playback"]
    # The play that was cut, or None when nothing played.
    id: str | None
    # The plays that never started, including plays whose bytes the client already has.
    dropped: list[str]


class Error(tp.TypedDict):
    type: tp.Literal["error"]
    message: str


class Ended(tp.TypedDict):
    type: tp.Literal["ended"]
    reason: EndedReason


EngineFrame = (
    State
    | Transcript
    | TurnStart
    | TurnEnd
    | TurnDropped
    | Ignored
    | Play
    | PlayDone
    | PausePlayback
    | ResumePlayback
    | StopPlayback
    | Error
    | Ended
)


class FrameError(Exception):
    """A text frame that is not JSON, or a known frame with a missing or wrong field."""


def _text(body: dict[str, JsonValue], key: str) -> str:
    if key not in body or not isinstance(body[key], str) or not body[key]:
        raise FrameError(f"{body['type']}: `{key}` must be text that is not empty")
    return str(body[key])


def _start_session(body: dict[str, JsonValue]) -> StartSession:
    playback = body["playback"] if "playback" in body else None
    delivery = playback["delivery"] if isinstance(playback, dict) and "delivery" in playback else None
    if not isinstance(playback, dict) or not isinstance(delivery, str) or delivery not in ("url", "bytes"):
        raise FrameError("start_session: `playback.delivery` must be `url` or `bytes`")
    formats = playback["formats"] if "formats" in playback else None
    if not isinstance(formats, list) or not all(isinstance(name, str) for name in formats):
        raise FrameError("start_session: `playback.formats` must be a list of format names")
    barge_in = body["barge_in"] if "barge_in" in body else None
    if barge_in is not None and not isinstance(barge_in, bool):
        raise FrameError("start_session: `barge_in` must be true or false")
    return {
        "type": "start_session",
        "client": str(body["client"]) if "client" in body else "",
        "mic_supported": "audio" in body and body["audio"] == MIC_AUDIO,
        "delivery": delivery,
        "formats": [str(name) for name in formats],
        "barge_in": barge_in,
    }


def _playback_report(body: dict[str, JsonValue]) -> PlaybackReport:
    state = body["state"] if "state" in body else None
    if isinstance(state, str) and state in ("started", "finished", "failed"):
        return {"type": "playback", "id": _text(body, "id"), "state": state}
    if state == "stopped_by_user":
        # The id is optional here: the user stopped whatever played.
        play_id = body["id"] if "id" in body else ""
        return {"type": "playback", "id": play_id if isinstance(play_id, str) else "", "state": "stopped_by_user"}
    raise FrameError("playback: `state` must be started, finished, failed, or stopped_by_user")


def parse_client_frame(raw: str) -> ClientFrame | None:
    """The frame in `raw`, or None for a frame type that the engine does not know."""
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise FrameError("the frame is not JSON") from None
    if not isinstance(body, dict) or "type" not in body or not isinstance(body["type"], str):
        raise FrameError("the frame has no `type`")
    kind = body["type"]
    if kind == "start_session":
        return _start_session(body)
    if kind == "speak":
        return {"type": "speak", "id": _text(body, "id"), "text": _text(body, "text")}
    if kind == "playback":
        return _playback_report(body)
    if kind == "end_turn":
        return {"type": "end_turn"}
    if kind == "end_session":
        return {"type": "end_session"}
    return None
