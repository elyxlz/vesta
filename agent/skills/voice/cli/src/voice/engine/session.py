"""The `/voice/session` socket: one session for each socket, and a session shares nothing.

A session composes the pure parts: `turns` decides what text does, `playback` tracks what the
client's speaker did, and this module moves frames between the client, the STT stream, the judge,
and the TTS provider. Everything is read once, at session start: the selected providers, their
settings, the judge, and the behaviors. A change applies to the next session.

One loop handles every event in order (client frames, STT events, verdicts, the hold timer), so
no two decisions run at the same time. Mic audio does not wait for that loop: the client reader
hands it straight to the STT stream.
"""

import asyncio
import contextlib
import dataclasses as dc
import json
import logging
import os
import secrets
import time
import typing as tp

import aiohttp
from aiohttp import web

from voice import appkeys, providers
from voice import config as voice_config
from voice.providers.base import Judge, Line, Question, SttEvent, SttOpenError, SttStream, TtsError, TtsProvider, Verdict
from voice.settings import Domain

from . import behavior, buffers, frames, playback, turns

logger = logging.getLogger("voice.session")

# How many finished lines the judge sees as context.
RECENT_LINES = 2
WS_HEARTBEAT_SECS = 30.0
PLAY_URL_PREFIX = "/voice/play/"
PLAY_TOKEN_BYTES = 16
DEFAULT_AGENT_NAME = "agent"


class ClientItem(tp.TypedDict):
    kind: tp.Literal["client"]
    frame: frames.ClientFrame


class SttItem(tp.TypedDict):
    kind: tp.Literal["stt"]
    event: SttEvent


class JudgedItem(tp.TypedDict):
    kind: tp.Literal["judged"]
    text: str


class SynthFailedItem(tp.TypedDict):
    kind: tp.Literal["synth_failed"]
    token: str
    message: str


class SignalItem(tp.TypedDict):
    kind: tp.Literal["tick", "client_closed", "task_failed"]


Item = ClientItem | SttItem | JudgedItem | SynthFailedItem | SignalItem
# How one handled item ends the session: with an `ended` reason, silently when the client is
# gone, or with an `error` when a part of the engine itself failed.
Outcome = frames.EndedReason | tp.Literal["client_gone", "engine_failed"] | None
ENGINE_FAILED = "the engine failed and this session is over; open a new session"


@dc.dataclass(frozen=True)
class TtsLink:
    provider: TtsProvider
    creds: dict[str, str]
    settings: Domain
    voice: str
    audio_format: str


@dc.dataclass(frozen=True)
class JudgeLink:
    provider: Judge
    creds: dict[str, str]
    settings: Domain


@dc.dataclass
class Session:
    ws: web.WebSocketResponse
    http: aiohttp.ClientSession
    # The app's token map. This session adds its own tokens and removes them when it ends.
    plays: dict[str, buffers.PlayBuffer]
    stt: SttStream
    tts: TtsLink | None
    judge: JudgeLink | None
    delivery: frames.Delivery
    barge_in: bool
    agent_name: str
    inbox: asyncio.Queue[Item] = dc.field(default_factory=asyncio.Queue)
    turn: turns.TurnState = dc.field(default_factory=turns.TurnState)
    # What the client's speaker did with the plays of this session.
    speaker: playback.PlaybackState = dc.field(default_factory=playback.PlaybackState)
    # Play token -> its synthesis task.
    synthesis: dict[str, asyncio.Task[None]] = dc.field(default_factory=dict)
    recent: list[Line] = dc.field(default_factory=list)
    # The judge call for the newest live text of the open segment, and the verdict for one
    # exact text.
    asking: tuple[str, asyncio.Task[None]] | None = None
    verdict: tuple[str, Verdict | None] | None = None
    wire: frames.StateValue | None = None
    tasks: set[asyncio.Task[None]] = dc.field(default_factory=set)
    # `bytes` delivery only: the plays to send, and the task that sends them one at a time.
    byte_queue: asyncio.Queue[playback.Play] = dc.field(default_factory=asyncio.Queue)
    byte_sender: asyncio.Task[None] | None = None


class _UnsupportedFormatError(Exception):
    pass


async def _send(ws: web.WebSocketResponse, frame: frames.EngineFrame) -> None:
    with contextlib.suppress(ConnectionError):
        await ws.send_str(json.dumps(frame))


def _spawn(session: Session, work: tp.Coroutine[None, None, None]) -> asyncio.Task[None]:
    task = asyncio.create_task(work)
    session.tasks.add(task)
    task.add_done_callback(lambda done: _task_done(session, done))
    return task


def _task_done(session: Session, task: asyncio.Task[None]) -> None:
    session.tasks.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        # A part of the session died. End the session so the client is not left on a socket
        # that no longer listens.
        logger.error("voice session task failed", exc_info=error)
        session.inbox.put_nowait({"kind": "task_failed"})


# --- session start ---


async def _await_start(ws: web.WebSocketResponse) -> frames.StartSession | None:
    """Read frames until a valid `start_session`. Every other frame before it gets `error`."""
    async for msg in ws:
        if msg.type not in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
            continue
        message = "the first frame must be start_session"
        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                frame = frames.parse_client_frame(msg.data)
            except frames.FrameError as e:
                frame = None
                message = str(e)
            if frame is not None and frame["type"] == "start_session":
                return frame
        await _send(ws, {"type": "error", "message": message})
    return None


def _tts_link(entry: Domain, wanted_formats: list[str]) -> TtsLink | None:
    """The TTS provider of this session, or None when the role is off or has no provider: a
    session needs TTS only for `speak`. Raises when the provider can make none of the formats."""
    name = voice_config.provider_name(entry)
    if name is None or not voice_config.is_enabled(entry):
        return None
    provider = providers.get_tts(name)
    if provider is None:
        return None
    audio_format = next((f for f in wanted_formats if f in provider.formats and f in frames.PLAY_FORMATS), None)
    if audio_format is None:
        raise _UnsupportedFormatError
    settings = voice_config.provider_settings(entry)
    return TtsLink(provider, voice_config.provider_creds(entry, name), settings, providers.selected_voice(provider, entry), audio_format)


def _judge_link(entry: Domain) -> JudgeLink | None:
    name = voice_config.provider_name(entry)
    if name is None or not voice_config.is_enabled(entry):
        return None
    provider = providers.get_judge(name)
    if provider is None:
        return None
    return JudgeLink(provider, voice_config.provider_creds(entry, name), voice_config.provider_settings(entry))


async def _open(app: web.Application, ws: web.WebSocketResponse, start: frames.StartSession) -> Session | frames.EndedReason:
    config = voice_config.load(app[appkeys.DATA_DIR])
    stt_entry = config["stt"]
    stt_name = voice_config.provider_name(stt_entry)
    stt_provider = providers.get_stt(stt_name)
    if stt_name is None or stt_provider is None or not voice_config.is_enabled(stt_entry):
        return "not_configured"
    if not start["mic_supported"]:
        return "unsupported_format"
    try:
        tts = _tts_link(config["tts"], start["formats"])
    except _UnsupportedFormatError:
        return "unsupported_format"
    try:
        stt = await stt_provider.open(voice_config.provider_creds(stt_entry, stt_name), voice_config.provider_settings(stt_entry))
    except SttOpenError as e:
        logger.warning("stt open failed for %s (%s): %s", start["client"], stt_name, e)
        return "stt_limit" if e.reason == "limit" else "stt_failed"
    return Session(
        ws=ws,
        http=app[appkeys.HTTP],
        plays=app[appkeys.PLAYS],
        stt=stt,
        tts=tts,
        judge=_judge_link(config["judge"]),
        delivery=start["delivery"],
        barge_in=behavior.barge_in_allowed(config["behavior"], start["barge_in"]),
        agent_name=os.environ["AGENT_NAME"] if "AGENT_NAME" in os.environ else DEFAULT_AGENT_NAME,
    )


# --- the two readers ---


async def _read_client(session: Session) -> None:
    async for msg in session.ws:
        if msg.type == aiohttp.WSMsgType.BINARY:
            await session.stt.send(msg.data)
        elif msg.type == aiohttp.WSMsgType.TEXT:
            try:
                frame = frames.parse_client_frame(msg.data)
            except frames.FrameError as e:
                await _send(session.ws, {"type": "error", "message": str(e)})
                continue
            if frame is not None:
                await session.inbox.put({"kind": "client", "frame": frame})
    await session.inbox.put({"kind": "client_closed"})


async def _read_stt(session: Session) -> None:
    async for event in session.stt.events():
        await session.inbox.put({"kind": "stt", "event": event})


# --- playback ---


def _remember(session: Session, by: str, text: str) -> None:
    session.recent = [*session.recent, {"by": by, "text": text}][-RECENT_LINES:]


async def _synthesize(session: Session, tts: TtsLink, play: playback.Play, buffer: buffers.PlayBuffer) -> None:
    audio = tts.provider.synthesize(play.text, tts.voice, tts.audio_format, tts.creds, tts.settings, session.http)
    try:
        await buffers.fill(buffer, audio)
    except TtsError as e:
        await session.inbox.put({"kind": "synth_failed", "token": play.token, "message": str(e)})


async def _send_bytes(session: Session, audio_format: str) -> None:
    """`bytes` delivery: all the bytes of one play go out before the next `play` frame, so the
    binary frames always belong to the last play that has no `play_done` yet."""
    while True:
        play = await session.byte_queue.get()
        if play.token not in session.plays:
            continue
        await _send(session.ws, {"type": "play", "id": play.id, "format": audio_format})
        async for chunk in buffers.read(session.plays[play.token]):
            with contextlib.suppress(ConnectionError):
                await session.ws.send_bytes(chunk)
        await _send(session.ws, {"type": "play_done", "id": play.id})


async def _send_plays(session: Session, tts: TtsLink, plays: tuple[playback.Play, ...]) -> None:
    for play in plays:
        if session.delivery == "bytes":
            await session.byte_queue.put(play)
        else:
            await _send(session.ws, {"type": "play", "id": play.id, "format": tts.audio_format, "url": PLAY_URL_PREFIX + play.token})


async def _on_speak(session: Session, frame: frames.Speak) -> None:
    tts = session.tts
    if tts is None:
        await _send(session.ws, {"type": "error", "message": "tts is off or has no provider; this session cannot speak"})
        return
    play = playback.Play(id=frame["id"], text=frame["text"], token=secrets.token_urlsafe(PLAY_TOKEN_BYTES))
    buffer = buffers.PlayBuffer(tts.audio_format)
    session.plays[play.token] = buffer
    session.synthesis[play.token] = _spawn(session, _synthesize(session, tts, play, buffer))
    session.speaker, to_send = playback.speak(session.speaker, play, hold=session.turn.phase == "user_turn")
    await _send_plays(session, tts, to_send)


async def _release_held(session: Session) -> None:
    session.speaker, to_send = playback.release(session.speaker)
    if session.tts is not None:
        await _send_plays(session, session.tts, to_send)


async def _forget(session: Session, token: str) -> None:
    """End one play of this session: its synthesis stops, and its token answers 404."""
    task = session.synthesis.pop(token, None)
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    session.plays.pop(token, None)


async def _stop_playback(session: Session) -> None:
    stopped = playback.stop(session.speaker)
    session.speaker = stopped.state
    if session.byte_sender is not None and session.tts is not None:
        # The sender can be in the middle of a play: end it, so no byte follows `stop_playback`.
        session.byte_sender.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await session.byte_sender
        session.byte_queue = asyncio.Queue()
        session.byte_sender = _spawn(session, _send_bytes(session, session.tts.audio_format))
    for play in (*((stopped.cut,) if stopped.cut is not None else ()), *stopped.dropped):
        await _forget(session, play.token)
    if stopped.cut is not None:
        _remember(session, session.agent_name, stopped.cut.text)
    cut_id = stopped.cut.id if stopped.cut is not None else None
    await _send(session.ws, {"type": "stop_playback", "id": cut_id, "dropped": [play.id for play in stopped.dropped]})


async def _on_report(session: Session, frame: frames.PlaybackReport) -> None:
    if frame["state"] == "stopped_by_user":
        await _step(session, {"kind": "stopped_by_user"})
        return
    session.speaker, over = playback.report(session.speaker, frame["id"], frame["state"])
    if over is not None:
        if over.started:
            # The play was heard, in whole or in part: it becomes a line the judge can see.
            _remember(session, session.agent_name, over.text)
        # The speaker is done with this play, so the session holds its audio no longer.
        await _forget(session, over.token)
    await _sync_state(session)


# --- turns ---


async def _sync_state(session: Session) -> None:
    value = turns.wire_state(session.turn, playback.speaking(session.speaker))
    if value != session.wire:
        session.wire = value
        await _send(session.ws, {"type": "state", "value": value})


async def _tick_after_hold(session: Session) -> None:
    await asyncio.sleep(turns.HOLD_WAIT_MS / 1000)
    await session.inbox.put({"kind": "tick"})


async def _apply(session: Session, action: turns.Action) -> None:
    if action["type"] == "stop_now":
        await _stop_playback(session)
        return
    await _send(session.ws, action)
    if action["type"] == "pause_playback":
        _spawn(session, _tick_after_hold(session))
    elif action["type"] == "turn_end":
        _remember(session, "user", action["text"])
        await _release_held(session)
    elif action["type"] == "turn_dropped":
        await _release_held(session)


async def _step(session: Session, event: turns.TurnEvent) -> None:
    session.turn, actions = turns.step(
        session.turn,
        event,
        speaking=playback.speaking(session.speaker),
        barge_in=session.barge_in,
        now=time.monotonic(),
    )
    for action in actions:
        await _apply(session, action)
    await _sync_state(session)


def _question(session: Session, text: str) -> Question:
    running = playback.saying(session.speaker)
    return {
        "agent_name": session.agent_name,
        "recent": list(session.recent),
        "agent_saying": running.text if running is not None else None,
        "user_saying": text,
    }


async def _ask(session: Session, judge: JudgeLink, text: str) -> None:
    verdict = await judge.provider.ask(_question(session, text), judge.creds, judge.settings, session.http)
    session.verdict = (text, verdict)
    await session.inbox.put({"kind": "judged", "text": text})


def _drop_pending_ask(session: Session) -> None:
    if session.asking is not None:
        session.asking[1].cancel()
        session.asking = None


async def _on_live(session: Session, text: str) -> None:
    if not text.strip():
        return
    await _send(session.ws, {"type": "transcript", "text": text})
    await _step(session, {"kind": "live", "text": text})
    if session.judge is None:
        await _step(session, {"kind": "judged", "text": text, "verdict": None})
        return
    # A verdict counts only for the exact text it was asked about, so new text replaces the call.
    _drop_pending_ask(session)
    session.asking = (text, _spawn(session, _ask(session, session.judge, text)))


async def _on_judged(session: Session, text: str) -> None:
    if session.asking is None or session.asking[0] != text or session.verdict is None or session.verdict[0] != text:
        return
    await _step(session, {"kind": "judged", "text": text, "verdict": session.verdict[1]})


async def _verdict_for(session: Session, text: str) -> Verdict | None:
    """The verdict for a committed text: the one at hand, the pending one, or a new one."""
    judge = session.judge
    if judge is None or not text:
        return None
    if session.verdict is None or session.verdict[0] != text:
        if session.asking is not None and session.asking[0] == text:
            await session.asking[1]
        else:
            return await judge.provider.ask(_question(session, text), judge.creds, judge.settings, session.http)
    return session.verdict[1] if session.verdict is not None and session.verdict[0] == text else None


async def _on_committed(session: Session, text: str) -> None:
    verdict = await _verdict_for(session, text)
    _drop_pending_ask(session)
    session.verdict = None
    # The segment is over, so its live text is over, whatever the turn rules decide about it.
    await _send(session.ws, {"type": "transcript", "text": ""})
    await _step(session, {"kind": "committed", "text": text, "verdict": verdict})


# --- the loop ---


async def _on_client(session: Session, frame: frames.ClientFrame) -> Outcome:
    if frame["type"] == "start_session":
        await _send(session.ws, {"type": "error", "message": "start_session was already sent"})
    elif frame["type"] == "speak":
        await _on_speak(session, frame)
    elif frame["type"] == "playback":
        await _on_report(session, frame)
    elif frame["type"] == "end_turn":
        await session.stt.commit()
    else:
        return "client_ended"
    return None


async def _on_stt(session: Session, event: SttEvent) -> Outcome:
    if event["kind"] == "closed":
        return "stt_failed"
    if event["kind"] == "transcription":
        await _on_live(session, event["text"])
    else:
        await _on_committed(session, event["text"])
    return None


async def _on_synth_failed(session: Session, item: SynthFailedItem) -> None:
    """The play stays with the client, which reports `failed` for it. A play that was still
    held never reaches the client, so it goes now."""
    await _send(session.ws, {"type": "error", "message": item["message"]})
    session.speaker, was_held = playback.drop_held(session.speaker, item["token"])
    if was_held:
        await _forget(session, item["token"])


async def _handle(session: Session, item: Item) -> Outcome:
    if item["kind"] == "client":
        return await _on_client(session, item["frame"])
    if item["kind"] == "stt":
        return await _on_stt(session, item["event"])
    if item["kind"] == "client_closed":
        return "client_gone"
    if item["kind"] == "task_failed":
        return "engine_failed"
    if item["kind"] == "judged":
        await _on_judged(session, item["text"])
    elif item["kind"] == "tick":
        await _step(session, {"kind": "tick"})
    else:
        await _on_synth_failed(session, item)
    return None


async def _run(session: Session) -> Outcome:
    _spawn(session, _read_client(session))
    _spawn(session, _read_stt(session))
    if session.delivery == "bytes" and session.tts is not None:
        session.byte_sender = _spawn(session, _send_bytes(session, session.tts.audio_format))
    await _sync_state(session)
    while True:
        outcome = await _handle(session, await session.inbox.get())
        if outcome is not None:
            return outcome


async def _close(session: Session) -> None:
    tasks = list(session.tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await session.stt.close()
    for token in list(session.synthesis):
        session.plays.pop(token, None)


async def voice_session(request: web.Request) -> web.WebSocketResponse:
    # Mic PCM and encoded audio do not compress, so deflate would only cost time on each frame.
    ws = web.WebSocketResponse(heartbeat=WS_HEARTBEAT_SECS, compress=False)
    await ws.prepare(request)
    start = await _await_start(ws)
    if start is None:
        return ws
    opened = await _open(request.app, ws, start)
    if not isinstance(opened, Session):
        await _send(ws, {"type": "ended", "reason": opened})
        await ws.close()
        return ws
    try:
        outcome = await _run(opened)
        if outcome == "engine_failed":
            await _send(ws, {"type": "error", "message": ENGINE_FAILED})
        elif outcome is not None and outcome != "client_gone":
            await _send(ws, {"type": "ended", "reason": outcome})
    finally:
        await asyncio.shield(_close(opened))
    await ws.close()
    return ws


async def voice_play(request: web.Request) -> web.StreamResponse:
    """The audio of one play, for `url` delivery. A token answers 404 once its play is over or
    stopped, and after its session ends."""
    plays = request.app[appkeys.PLAYS]
    token = request.match_info["token"]
    if token not in plays:
        return web.json_response({"error": "unknown play, or its session ended"}, status=404)
    buffer = plays[token]
    # Wait for the first audio before the headers, so a failed synthesis still gets an error status.
    if not await buffers.first_chunk(buffer):
        return web.json_response({"error": buffer.error or "the play has no audio"}, status=502)
    response = web.StreamResponse(headers={"Content-Type": frames.PLAY_FORMATS[buffer.audio_format]})
    await response.prepare(request)
    async for chunk in buffers.read(buffer):
        await response.write(chunk)
    await response.write_eof()
    return response
