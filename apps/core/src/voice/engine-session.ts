// One voice session over the voice engine socket (GET .../voice/session), shared by every
// client: the socket lifecycle, the engine's frames, the pre-open audio buffer, and the queue
// of plays the engine sends. The engine decides turns, barge-in, and when a reply plays; this
// session does what its frames say and reports what the speaker did. Platforms inject only how
// audio is captured, how the socket is dialed, and how a url is played.

import { adaptWebSocket, type SocketLike } from "../transport/websocket";
import { parseEngineFrame, type EngineFrame } from "./engine-frames";
import { createPlayQueue, type PlayQueue, type Speaker } from "./play-queue";

// About two seconds of 16 kHz 16-bit mono audio: frames captured before the socket opens
// are kept up to this, oldest dropped first.
export const MAX_PENDING_AUDIO_BYTES = 16_000 * 2 * 2;

export interface AudioCapture {
  // Starts the microphone and resolves once frames can flow; frames are raw 16 kHz 16-bit
  // mono PCM. Rejecting is the permission or hardware failure path. The voice session never
  // starts it twice at once, and stops it again after a start that a stop overtook.
  start: (onFrame: (pcm: ArrayBuffer) => void) => Promise<void>;
  // Turns off what the microphone holds now.
  stop: () => void;
}

export interface EngineSessionDeps {
  // Async and re-asked on every start, so the token in the URL is fresh at dial time rather
  // than captured at construction.
  buildUrl: () => Promise<string>;
  // Defaults to the platform WebSocket; tests inject a fake.
  createSocket?: (url: string) => SocketLike;
  capture: AudioCapture;
  speaker: Speaker;
  // The url a speaker can fetch for a play; the engine names a play as a path on its service.
  playUrl: (path: string) => Promise<string>;
  // The name the engine logs this client under.
  client: string;
}

export interface EngineSessionCallbacks {
  // The live text of what the microphone hears now, and "" when that text is over.
  onTranscript: (text: string) => void;
  onTurnStart: () => void;
  // A turn said to the agent ended. The text is never empty.
  onTurnEnd: (text: string) => void;
  // A started turn ended and goes to nobody.
  onTurnDropped: () => void;
  onSpeakingChange: (speaking: boolean) => void;
  // One play could not play. The session continues.
  onPlayFailed: (message: string) => void;
  // The session is over and did not end by `stop`.
  onError: (message: string) => void;
  onActiveChange: (active: boolean) => void;
}

export interface EngineSessionOptions {
  // False for a session in which the user's voice never stops a reply (dictation).
  bargeIn: boolean;
}

export interface EngineSession {
  start: () => Promise<void>;
  stop: () => void;
  // True once the microphone is up and the engine accepted the session.
  active: () => boolean;
  // Asks the engine to say a reply. The engine decides when it plays.
  speak: (text: string) => void;
  // The user stopped the speech on the device.
  stopSpeech: () => void;
  speaking: () => boolean;
}

const CONNECT_FAILED = "Could not connect to live voice";
const CLOSED = "Voice connection closed unexpectedly";
const PLAYBACK_FAILED = "Voice playback failed";
// Why the engine ended a session that the client did not end.
const ENDED_MESSAGES: Record<string, string> = {
  not_configured: "Speech-to-text is off or not set up",
  stt_failed: "The transcription service failed",
  stt_limit:
    "The speech provider is at its limit of sessions. Try again in a moment",
  unsupported_format: "This voice setup cannot make audio that this app plays",
};

export function createEngineSession(
  deps: EngineSessionDeps,
  callbacks: EngineSessionCallbacks,
  options: EngineSessionOptions,
): EngineSession {
  let state: "idle" | "starting" | "active" = "idle";
  // Bumped by stop; a start still in flight compares its own generation and abandons
  // quietly instead of throwing at the caller that asked to stop.
  let generation = 0;
  let socket: SocketLike | null = null;
  let socketOpen = false;
  // Settle the start: the engine's first state accepts the session, and an `ended` or a
  // close before it refuses.
  let accept: (() => void) | null = null;
  let refuse: ((reason: Error) => void) | null = null;
  let pending: ArrayBuffer[] = [];
  let pendingBytes = 0;
  // Replies asked for while the session starts; sent when the engine accepts it.
  let waitingReplies: string[] = [];
  let replies = 0;
  // The engine's error and the speaker can both report one failed reply; the user hears of it once.
  const failedReplies = new Set<string>();
  const replyFailed = (id: string, message: string): void => {
    if (failedReplies.has(id)) return;
    failedReplies.add(id);
    callbacks.onPlayFailed(message);
  };

  // Read through a call, because the frames and the close change the state during an await.
  const phase = (): typeof state => state;

  const send = (frame: Record<string, unknown>): void => {
    if (socket && socketOpen) socket.send(JSON.stringify(frame));
  };

  const plays: PlayQueue = createPlayQueue({
    speaker: deps.speaker,
    resolveUrl: deps.playUrl,
    report: (id, report) => {
      send({ type: "playback", id, state: report });
    },
    onSpeakingChange: callbacks.onSpeakingChange,
    onFailed: (id) => {
      replyFailed(id, PLAYBACK_FAILED);
    },
  });

  const cleanup = (): void => {
    const wasActive = state === "active";
    state = "idle";
    socketOpen = false;
    pending = [];
    pendingBytes = 0;
    waitingReplies = [];
    failedReplies.clear();
    plays.stop();
    if (socket) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.close();
      socket = null;
    }
    deps.capture.stop();
    refuse?.(new Error(CONNECT_FAILED));
    accept = null;
    refuse = null;
    if (wasActive) callbacks.onActiveChange(false);
  };

  const fail = (message: string): void => {
    // Report before cleanup: cleanup fires onActiveChange(false), and a consumer that drops
    // its session reference on going inactive would otherwise miss this error.
    callbacks.onError(message);
    cleanup();
  };

  const onFrame = (frame: ArrayBuffer): void => {
    if (state === "idle") return;
    if (socket && socketOpen) {
      socket.send(frame);
      return;
    }
    while (
      pending.length > 0 &&
      pendingBytes + frame.byteLength > MAX_PENDING_AUDIO_BYTES
    ) {
      const dropped = pending.shift();
      pendingBytes -= dropped?.byteLength ?? 0;
    }
    if (frame.byteLength <= MAX_PENDING_AUDIO_BYTES) {
      pending.push(frame);
      pendingBytes += frame.byteLength;
    }
  };

  const say = (text: string): void => {
    replies += 1;
    send({ type: "speak", id: `reply-${String(replies)}`, text });
  };

  // The session ended without this client's stop: a start in flight is refused with the
  // reason, and a running session fails with it.
  const endUnasked = (message: string, startMessage: string): void => {
    if (!refuse) {
      fail(message);
      return;
    }
    const refuseStart = refuse;
    refuse = null;
    accept = null;
    refuseStart(new Error(startMessage));
  };

  const onEnded = (reason: string): void => {
    // The answer to this client's own end_session needs nothing.
    if (reason === "client_ended") return;
    const message = ENDED_MESSAGES[reason] ?? CLOSED;
    endUnasked(message, message);
  };

  const handleFrame = (frame: EngineFrame): void => {
    switch (frame.type) {
      case "state":
        accept?.();
        accept = null;
        refuse = null;
        break;
      case "transcript":
        callbacks.onTranscript(frame.text);
        break;
      case "turn_start":
        callbacks.onTurnStart();
        break;
      case "turn_end":
        callbacks.onTurnEnd(frame.text);
        break;
      case "turn_dropped":
        callbacks.onTurnDropped();
        break;
      case "play":
        plays.enqueue(frame.id, frame.url);
        break;
      case "pause_playback":
        plays.pause();
        break;
      case "resume_playback":
        plays.resume();
        break;
      case "stop_playback":
        plays.stop();
        break;
      case "error":
        // With an id, a reply the engine could not say: TTS is off, or its synthesis failed.
        if (frame.id === null) callbacks.onPlayFailed(frame.message);
        else replyFailed(frame.id, frame.message);
        break;
      case "ended":
        onEnded(frame.reason);
        break;
    }
  };

  const dial = (url: string): Promise<void> => {
    const dialed = (deps.createSocket ?? adaptWebSocket)(url);
    socket = dialed;
    const accepted = new Promise<void>((resolve, reject) => {
      accept = resolve;
      refuse = reject;
    });
    dialed.onopen = () => {
      socketOpen = true;
      send({
        type: "start_session",
        client: deps.client,
        audio: { encoding: "pcm_s16le", sample_rate: 16000, channels: 1 },
        playback: { delivery: "url", formats: ["mp3_22050"] },
        barge_in: options.bargeIn,
      });
      const buffered = pending;
      pending = [];
      pendingBytes = 0;
      for (const frame of buffered) dialed.send(frame);
    };
    dialed.onmessage = (data) => {
      const frame = parseEngineFrame(data);
      if (frame) handleFrame(frame);
    };
    dialed.onclose = () => {
      if (socket === dialed) endUnasked(CLOSED, CONNECT_FAILED);
    };
    return accepted;
  };

  const start = async (): Promise<void> => {
    if (state !== "idle") return;
    state = "starting";
    const myGeneration = ++generation;
    pending = [];
    pendingBytes = 0;

    try {
      const url = await deps.buildUrl();
      if (generation !== myGeneration) return;
      await Promise.all([deps.capture.start(onFrame), dial(url)]);
      // A stop, or a session that the engine ended while the microphone was still coming
      // up, already cleaned up: this start must not bring the session back.
      if (generation !== myGeneration || phase() !== "starting") return;
      state = "active";
      callbacks.onActiveChange(true);
      const waiting = waitingReplies;
      waitingReplies = [];
      for (const text of waiting) say(text);
    } catch (cause) {
      cleanup();
      if (generation !== myGeneration) return;
      throw cause;
    }
  };

  return {
    start,
    stop: () => {
      if (state === "idle") return;
      generation += 1;
      send({ type: "end_session" });
      cleanup();
    },
    active: () => state === "active",
    speak: (text) => {
      if (state === "active") say(text);
      else if (state === "starting") waitingReplies.push(text);
    },
    stopSpeech: () => {
      // The engine answers with stop_playback. A reply that it holds for a user turn is
      // not a part of that stop: it plays when the turn ends.
      send({ type: "playback", state: "stopped_by_user" });
      plays.stop();
    },
    speaking: () => plays.speaking(),
  };
}
