// The behavior model over one microphone and one speaker: composes the STT session and the
// TTS queue and owns the decisions every client must agree on. Two modes. Dictation
// accumulates turns into the composer and sends one message when the user confirms, or
// drops them when the user discards. A conversation is duplex: each turn sends as it ends,
// a user turn always cuts the reply being spoken, and a stretch of silence ends it. Clients
// adapt audio I/O and render the state; they no longer decide.

import {
  createSttSession,
  type AudioCapture,
  type SttSession,
  type VoiceSocketLike,
} from "./stt-session";
import { createTtsQueue, type SpeechPlayer, type TtsQueue } from "./tts-queue";

export type VoiceMode = "dictation" | "conversation";

export interface VoiceSessionSettings {
  // Dictation cuts a reply on a user turn only when this is set; a conversation always cuts.
  interruptTts: boolean;
  // A conversation with no user turn for this long ends itself. 0 disables. Dictation
  // ignores it, since the user ends dictation by hand.
  inactivityMs: number;
  // A conversation yields the floor to the user: while their turn is live it reports them as
  // speaking (onUserSpeakingChange, which clients mirror to the agent) and holds replies off
  // the speaker until the turn ends. Off keeps the duplex free-for-all. Dictation ignores it.
  yieldToUser: boolean;
}

export interface VoiceSessionDeps {
  buildUrl: () => Promise<string>;
  createSocket: (url: string) => VoiceSocketLike;
  capture: AudioCapture;
  player: SpeechPlayer;
  setTimer: (fn: () => void, ms: number) => number;
  clearTimer: (handle: number) => void;
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
  // A conversation ended itself after the inactivity window; the client tells the user.
  onInactivityStop: () => void;
  // The user's live turn in a yielding conversation: true at turn start, false at turn end or
  // when the session ends however it ends. Clients forward it to the agent's chat channel so
  // the agent holds its reply while the user is talking. Never fires for dictation.
  onUserSpeakingChange: (speaking: boolean) => void;
}

export interface VoiceSession {
  start: (mode: VoiceMode) => Promise<void>;
  // Dictation sends what it captured; a conversation just ends. Both drop any in-flight
  // partial turn.
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
  let stt: SttSession | null = null;
  let mode: VoiceMode | null = null;
  let idleTimer: number | null = null;
  // The user's live turn while a conversation yields: replies land in `held` instead of the
  // speaker, and the change is reported so the client can mirror it to the agent.
  let userTurn = false;
  let held: string[] = [];

  const setUserTurn = (value: boolean): void => {
    if (userTurn === value) return;
    userTurn = value;
    callbacks.onUserSpeakingChange(value);
  };

  const queue: TtsQueue = createTtsQueue(deps.player, {
    onSpeakingChange: callbacks.onSpeakingChange,
    onError: callbacks.onError,
  });

  const clearIdleTimer = (): void => {
    if (idleTimer !== null) {
      deps.clearTimer(idleTimer);
      idleTimer = null;
    }
  };

  const clear = (): void => {
    clearIdleTimer();
    stt = null;
    // A held reply belonged to the session that just ended; it is dropped, not spoken late.
    held = [];
    setUserTurn(false);
    if (mode !== null) {
      mode = null;
      callbacks.onModeChange(null);
    }
  };

  const end = (send: boolean): void => {
    const session = stt;
    if (!session) return;
    const dictation = mode === "dictation";
    const captured = session.stop();
    clear();
    if (send && dictation && captured) callbacks.onSend(captured);
  };

  const start = async (mode_: VoiceMode): Promise<void> => {
    if (stt) return;
    mode = mode_;
    callbacks.onModeChange(mode_);
    // A new session takes the speaker: whatever was playing stops.
    queue.stop();

    const conversation = mode_ === "conversation";
    const armIdleTimer = (): void => {
      const { inactivityMs } = settings();
      if (!conversation || !inactivityMs) return;
      clearIdleTimer();
      idleTimer = deps.setTimer(() => {
        idleTimer = null;
        end(false);
        callbacks.onInactivityStop();
      }, inactivityMs);
    };

    const session = createSttSession(
      {
        buildUrl: deps.buildUrl,
        createSocket: deps.createSocket,
        capture: deps.capture,
      },
      {
        onTranscript: callbacks.onTranscript,
        onTurnStart: () => {
          if (conversation || settings().interruptTts) queue.stop();
          if (conversation && settings().yieldToUser) setUserTurn(true);
        },
        onTurnEnd: (text) => {
          if (!conversation) return;
          // The floor returns before the send goes out, so the agent's speaking gate is open
          // by the time the message reaches it; replies held during the turn play now.
          setUserTurn(false);
          const pending = held;
          held = [];
          for (const reply of pending) queue.speak(reply);
          if (!text) return;
          callbacks.onSend(text);
          armIdleTimer();
        },
        onError: (message) => {
          if (stt !== session) return;
          clear();
          callbacks.onError(message);
        },
        onActiveChange: (active) => {
          if (!active && stt === session) clear();
          callbacks.onListeningChange(active);
        },
      },
      { accumulate: !conversation },
    );

    stt = session;
    try {
      await session.start();
    } catch (cause) {
      if (stt === session) clear();
      throw cause;
    }
    if (stt === session) armIdleTimer();
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
    listening: () => stt?.active() ?? false,
    speak: (text) => {
      if (userTurn) {
        held.push(text);
        return;
      }
      queue.speak(text);
    },
    prefetch: (text) => {
      queue.prefetch(text);
    },
    stopSpeech: () => {
      held = [];
      queue.stop();
    },
    speaking: () => queue.speaking(),
  };
}
