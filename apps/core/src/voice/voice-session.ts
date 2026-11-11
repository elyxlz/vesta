// The behavior model over one microphone and one speaker, shared by every client. A voice
// session is one session of the voice engine, which decides turns, barge-in, and when a reply
// plays. This model owns what the engine does not know: the two modes and where a turn goes.
// Dictation accumulates turns into the composer and sends one message when the user confirms,
// or drops them when the user discards. A conversation sends each turn as it ends, tells the
// agent while the user holds the floor, and ends itself after a stretch of silence. Outside a
// session, a reply is read aloud through the queue of the streamed speech route. Clients adapt
// audio I/O and render the state; they do not decide.

import {
  createEngineSession,
  type EngineSession,
  type EngineSessionDeps,
} from "./engine-session";
import { serializeCapture } from "./microphone";
import { createTtsQueue, type TtsQueue } from "./tts-queue";

export type VoiceMode = "dictation" | "conversation";

export interface VoiceSessionSettings {
  // A conversation with no user turn for this long ends itself. 0 disables. Dictation
  // ignores it, since the user ends dictation by hand.
  inactivityMs: number;
}

export interface VoiceSessionDeps extends EngineSessionDeps {
  // Registers the text of a reply to read aloud outside a session, and resolves the url that
  // streams its audio.
  prepareSpeech: (text: string) => Promise<string>;
}

export interface VoiceSessionCallbacks {
  onTranscript: (text: string) => void;
  onSend: (text: string) => void;
  onError: (message: string) => void;
  // The mode is set the instant start is called, before the microphone opens, and cleared
  // when the session ends. A release that beats the microphone still reads as recording.
  onModeChange: (mode: VoiceMode | null) => void;
  onListeningChange: (listening: boolean) => void;
  onSpeakingChange: (speaking: boolean) => void;
  // A conversation with the wake word on: true while the engine waits for the phrase.
  onWakeWaitingChange: (waiting: boolean) => void;
  // A conversation ended itself after the inactivity window; the client tells the user.
  onInactivityStop: () => void;
  // The user's live turn in a conversation: true at turn start, false at turn end or when
  // the session ends however it ends. Clients forward it to the agent's chat channel so the
  // agent holds its reply while the user is talking. Never fires for dictation.
  onUserSpeakingChange: (speaking: boolean) => void;
}

export interface VoiceSession {
  start: (mode: VoiceMode) => Promise<void>;
  // Dictation sends what it captured, the turn in progress included; a conversation just
  // ends, and its turn in progress is dropped.
  stop: () => void;
  // Ends either mode and sends nothing.
  cancel: () => void;
  mode: () => VoiceMode | null;
  listening: () => boolean;
  speak: (text: string) => void;
  prefetch: (text: string) => void;
  stopSpeech: () => void;
  speaking: () => boolean;
}

export function createVoiceSession(
  deps: VoiceSessionDeps,
  callbacks: VoiceSessionCallbacks,
  settings: () => VoiceSessionSettings,
): VoiceSession {
  // Every engine session of this model shares the one microphone.
  const engineDeps: EngineSessionDeps = {
    ...deps,
    capture: serializeCapture(deps.capture),
  };
  let engine: EngineSession | null = null;
  let mode: VoiceMode | null = null;
  let idleTimer: ReturnType<typeof setTimeout> | null = null;
  let userTurn = false;
  // Dictation: the turns that ended, and the live text of the one in progress.
  let committed = "";
  let live = "";
  // The speaker serves the read-aloud queue outside a session and the engine's plays inside
  // one; the client hears one "speaking".
  let readingAloud = false;
  let sessionSpeaking = false;
  let speaking = false;

  const reportSpeaking = (): void => {
    const now = readingAloud || sessionSpeaking;
    if (now === speaking) return;
    speaking = now;
    callbacks.onSpeakingChange(now);
  };

  const readAloud: TtsQueue = createTtsQueue(
    {
      prepare: deps.prepareSpeech,
      play: (url, signal) => deps.speaker.play(url, signal, () => undefined),
    },
    {
      onSpeakingChange: (value) => {
        readingAloud = value;
        reportSpeaking();
      },
      onError: callbacks.onError,
    },
  );

  const setUserTurn = (value: boolean): void => {
    if (userTurn === value) return;
    userTurn = value;
    callbacks.onUserSpeakingChange(value);
  };

  const dictated = (): string =>
    committed && live ? `${committed} ${live}` : committed || live;

  const clearIdleTimer = (): void => {
    if (idleTimer !== null) {
      clearTimeout(idleTimer);
      idleTimer = null;
    }
  };

  const clear = (): void => {
    clearIdleTimer();
    engine = null;
    setUserTurn(false);
    if (mode !== null) {
      mode = null;
      callbacks.onModeChange(null);
    }
  };

  const end = (send: boolean): void => {
    const session = engine;
    if (!session) return;
    // Dictation sends the whole display, including a turn still in progress, since the user
    // confirmed what they see. A conversation's turns already went out as each one ended.
    const captured = mode === "dictation" ? dictated().trim() : "";
    session.stop();
    clear();
    if (send && captured) callbacks.onSend(captured);
  };

  const start = async (mode_: VoiceMode): Promise<void> => {
    if (engine) return;
    mode = mode_;
    callbacks.onModeChange(mode_);
    // A new session takes the speaker: whatever was read aloud stops.
    readAloud.stop();
    committed = "";
    live = "";

    const conversation = mode_ === "conversation";
    const armIdleTimer = (): void => {
      const { inactivityMs } = settings();
      if (!conversation || !inactivityMs) return;
      clearIdleTimer();
      idleTimer = setTimeout(() => {
        idleTimer = null;
        end(false);
        callbacks.onInactivityStop();
      }, inactivityMs);
    };

    const session = createEngineSession(
      engineDeps,
      {
        onTranscript: (text) => {
          live = text;
          callbacks.onTranscript(conversation ? text : dictated());
        },
        onTurnStart: () => {
          if (conversation) setUserTurn(true);
        },
        onTurnEnd: (text) => {
          if (!conversation) {
            committed = committed ? `${committed} ${text}` : text;
            callbacks.onTranscript(committed);
            return;
          }
          // The floor returns before the send goes out, so the agent's speaking gate is open
          // by the time the message reaches it.
          setUserTurn(false);
          callbacks.onSend(text);
          armIdleTimer();
        },
        onTurnDropped: () => {
          setUserTurn(false);
        },
        onSpeakingChange: (value) => {
          sessionSpeaking = value;
          reportSpeaking();
        },
        onWakeWaitingChange: callbacks.onWakeWaitingChange,
        onPlayFailed: callbacks.onError,
        onError: (message) => {
          if (engine !== session) return;
          clear();
          callbacks.onError(message);
        },
        onActiveChange: (active) => {
          if (!active && engine === session) clear();
          callbacks.onListeningChange(active);
        },
      },
      // In dictation the user talks to the composer and holds the mic, so their voice never stops
      // a reply and no wake word is needed.
      { bargeIn: conversation, wakeWord: conversation },
    );

    engine = session;
    try {
      await session.start();
    } catch (cause) {
      if (engine === session) clear();
      throw cause;
    }
    if (engine === session) armIdleTimer();
  };

  return {
    start,
    stop: () => {
      end(true);
    },
    cancel: () => {
      end(false);
    },
    mode: () => mode,
    listening: () => engine?.active() ?? false,
    // During a session the engine speaks, so it knows that the agent has the floor.
    speak: (text) => {
      if (engine) engine.speak(text);
      else readAloud.speak(text);
    },
    prefetch: (text) => {
      if (!engine) readAloud.prefetch(text);
    },
    stopSpeech: () => {
      readAloud.stop();
      engine?.stopSpeech();
    },
    speaking: () => speaking,
  };
}
