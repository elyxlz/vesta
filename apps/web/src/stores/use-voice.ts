import { create } from "zustand";
import {
  Transcriber,
  prepareSpeech,
  streamSpeech,
  fetchSttStatus,
  fetchTtsStatus,
  type SttStatus,
  type TtsStatus,
} from "@/lib/voice";
import type { InputMethod, ServiceInfo } from "@vesta/core";
import { useToastStore } from "@/stores/use-toast";

// A conversation with no user turn for this long ends itself, since an open transcription
// stream costs by the minute; the user is told through a toast.
export const CONVERSATION_INACTIVITY_MS = 15 * 60_000;

// "dictation" (the mic button, Space): turns accumulate in the composer until the
// user confirms (sent as one message) or discards. "conversation": a duplex
// exchange, each turn sent as it ends, until the user ends it.
export type VoiceMode = "dictation" | "conversation";

interface VoiceState {
  // Agent context (set by VoiceStoreEffects)
  agentName: string | null;
  services: Record<string, ServiceInfo>;
  voiceRev: number | undefined;

  // Status
  sttStatus: SttStatus | null;
  ttsStatus: TtsStatus | null;
  sttAvailable: boolean;
  speechEnabled: boolean;

  // Recording (set at press time so a release that beats the microphone still lands)
  recordingMode: VoiceMode | null;
  // True once the microphone and the transcription socket are up.
  listening: boolean;
  liveTranscript: string;
  voiceError: string | null;

  // TTS
  isSpeaking: boolean;

  // Actions
  startVoice: (mode: VoiceMode) => void;
  // Confirms a dictation (sends what it captured) or ends a conversation.
  stopVoice: () => void;
  // Ends either mode and drops anything captured.
  cancelVoice: () => void;
  prefetch: (text: string) => void;
  speak: (text: string) => void;
  stopSpeech: () => void;
  // The chat's send, and its input reset: a voice mode takes the composer over, so typed
  // text is dropped when one starts.
  registerChat: (
    send: (text: string, inputMethod?: InputMethod) => void,
    clearInput: () => void,
  ) => void;

  // Status management
  patchStt: (patch: Partial<SttStatus>) => void;
  patchTts: (patch: Partial<TtsStatus>) => void;
  refreshVoiceStatus: () => void;

  // Internal (used by VoiceStoreEffects)
  _setAgentContext: (
    name: string | null,
    services: Record<string, ServiceInfo>,
    voiceRev: number | undefined,
  ) => void;
  _setSttStatus: (status: SttStatus | null) => void;
  _setTtsStatus: (status: TtsStatus | null) => void;
  _setVoiceError: (error: string | null) => void;
  _cleanup: () => void;
}

// Mutable refs outside React — safe because the store is a singleton
let transcriber: Transcriber | null = null;
let sendCallback: ((text: string, inputMethod?: InputMethod) => void) | null =
  null;
let clearInputCallback: (() => void) | null = null;
let inactivityTimer: ReturnType<typeof setTimeout> | null = null;
let ttsAbort: AbortController | null = null;
let ttsQueue: string[] = [];
let ttsProcessing = false;
// Bumped by stopSpeech to invalidate an in-flight processQueue loop, so a
// stop-then-speak sequence never leaves two loops draining ttsQueue at once.
let ttsEpoch = 0;
// Prepared TTS ids, warmed during the typing-pacing delay so playback can
// start the streamed GET immediately when the message is shown.
const ttsPrefetchCache = new Map<string, Promise<string>>();

function clearInactivityTimer() {
  if (inactivityTimer) {
    clearTimeout(inactivityTimer);
    inactivityTimer = null;
  }
}

function boolSetting(
  status: SttStatus | TtsStatus | null,
  key: string,
  fallback: boolean,
): boolean {
  const value = status?.settings?.find((s) => s.key === key)?.value;
  return typeof value === "boolean" ? value : fallback;
}

function deriveStatus(stt: SttStatus | null, tts: TtsStatus | null) {
  const sttAvailable = (stt?.configured && stt.enabled) ?? false;
  const speechEnabled = (tts?.configured && tts.enabled) ?? false;
  return { sttAvailable, speechEnabled };
}

export const useVoice = create<VoiceState>((set, get) => {
  const processQueue = async () => {
    const { agentName } = get();
    if (ttsProcessing || !agentName) return;
    ttsProcessing = true;
    const myEpoch = ttsEpoch;
    set({ isSpeaking: true });

    while (ttsQueue.length > 0 && ttsEpoch === myEpoch) {
      const text = ttsQueue.shift();
      if (text === undefined) break;
      const controller = new AbortController();
      ttsAbort = controller;
      try {
        const cached = ttsPrefetchCache.get(text);
        ttsPrefetchCache.delete(text);
        const preparedId = cached
          ? await cached.catch(() => undefined)
          : undefined;
        await streamSpeech(text, agentName, controller.signal, preparedId);
      } catch (err) {
        if (!controller.signal.aborted) {
          console.warn("[tts] playback failed:", err);
          set({ voiceError: "Voice playback failed" });
        }
      }
      if (ttsAbort === controller) ttsAbort = null;
    }

    // A newer epoch (stopSpeech) superseded this loop; the new loop owns the
    // shared flags, so exit without resetting them.
    if (ttsEpoch !== myEpoch) return;

    ttsProcessing = false;

    if (ttsQueue.length > 0) {
      void processQueue();
      return;
    }
    set({ isSpeaking: false });
  };

  return {
    agentName: null,
    services: {},
    voiceRev: undefined,

    sttStatus: null,
    ttsStatus: null,
    sttAvailable: false,
    speechEnabled: false,

    recordingMode: null,
    listening: false,
    liveTranscript: "",
    voiceError: null,

    isSpeaking: false,

    stopVoice: () => {
      const { recordingMode, liveTranscript } = get();
      if (recordingMode === null) return;
      const captured =
        recordingMode === "dictation" ? liveTranscript.trim() : "";
      get().cancelVoice();
      if (captured) sendCallback?.(captured, "voice");
    },

    cancelVoice: () => {
      transcriber?.stop();
      transcriber = null;
      clearInactivityTimer();
      set({ recordingMode: null, listening: false, liveTranscript: "" });
    },

    startVoice: (mode) => {
      if (get().recordingMode !== null) return;

      const { sttAvailable, agentName } = get();
      if (!sttAvailable || !agentName) {
        set({
          voiceError: "Voice input not configured — ask the agent to set it up",
        });
        return;
      }

      set({ voiceError: null, recordingMode: mode });
      clearInputCallback?.();

      // Stop TTS when recording starts
      get().stopSpeech();

      const dictation = mode === "dictation";

      const armInactivityTimer = () => {
        if (dictation) return;
        clearInactivityTimer();
        inactivityTimer = setTimeout(() => {
          inactivityTimer = null;
          get().stopVoice();
          useToastStore
            .getState()
            .show("info", "conversation ended after 15 minutes of silence");
        }, CONVERSATION_INACTIVITY_MS);
      };

      const stream = new Transcriber({
        agentName,
        accumulate: dictation,
        onTranscript: (text) => {
          set({ liveTranscript: text });
        },
        onTurnEnd: (text) => {
          if (dictation) return;
          sendCallback?.(text, "voice");
          set({ liveTranscript: "" });
          armInactivityTimer();
        },
        // A conversation is duplex, so speaking always cuts a reply; dictation honors the setting.
        onTurnStart: () => {
          if (!dictation || boolSetting(get().sttStatus, "interrupt_tts", true))
            get().stopSpeech();
        },
        onError: (err) => {
          set({ voiceError: err, recordingMode: null });
          transcriber?.stop();
          transcriber = null;
        },
      });

      transcriber = stream;
      stream
        .start()
        .then(() => {
          if (transcriber !== stream) return;
          set({ listening: true });
          armInactivityTimer();
        })
        .catch((err: unknown) => {
          const msg =
            err instanceof Error ? err.message : "Microphone access denied";
          set({ voiceError: msg, recordingMode: null });
          transcriber = null;
        });
    },

    prefetch: (text: string) => {
      const { speechEnabled, agentName } = get();
      if (!speechEnabled || !agentName) return;
      if (ttsPrefetchCache.has(text)) return;
      console.debug("[tts] prefetching:", text.slice(0, 60));
      ttsPrefetchCache.set(text, prepareSpeech(text, agentName));
    },

    speak: (text: string) => {
      const { speechEnabled, agentName } = get();
      if (!speechEnabled || !agentName) return;
      console.debug("[tts] queueing:", text.slice(0, 60));
      ttsQueue.push(text);
      void processQueue();
    },

    stopSpeech: () => {
      ttsQueue = [];
      ttsPrefetchCache.clear();
      ttsEpoch++;
      ttsAbort?.abort();
      ttsProcessing = false;
      set({ isSpeaking: false });
    },

    registerChat: (send, clearInput) => {
      sendCallback = send;
      clearInputCallback = clearInput;
    },

    patchStt: (patch) => {
      set((state) => {
        const sttStatus = state.sttStatus
          ? { ...state.sttStatus, ...patch }
          : state.sttStatus;
        return { sttStatus, ...deriveStatus(sttStatus, state.ttsStatus) };
      });
    },

    patchTts: (patch) => {
      set((state) => {
        const ttsStatus = state.ttsStatus
          ? { ...state.ttsStatus, ...patch }
          : state.ttsStatus;
        return { ttsStatus, ...deriveStatus(state.sttStatus, ttsStatus) };
      });
    },

    refreshVoiceStatus: () => {
      const { agentName } = get();
      if (!agentName) return;
      Promise.all([fetchSttStatus(agentName), fetchTtsStatus(agentName)])
        .then(([stt, tts]) => {
          set({
            sttStatus: stt,
            ttsStatus: tts,
            ...deriveStatus(stt, tts),
          });
        })
        .catch(() => {
          /* ignore */
        });
    },

    _setAgentContext: (name, services, voiceRev) => {
      set({ agentName: name, services, voiceRev });
    },

    _setSttStatus: (status) => {
      set((state) => ({
        sttStatus: status,
        ...deriveStatus(status, state.ttsStatus),
      }));
    },

    _setTtsStatus: (status) => {
      set((state) => ({
        ttsStatus: status,
        ...deriveStatus(state.sttStatus, status),
      }));
    },

    _setVoiceError: (error) => {
      set({ voiceError: error });
    },

    _cleanup: () => {
      get().cancelVoice();
      get().stopSpeech();
    },
  };
});
