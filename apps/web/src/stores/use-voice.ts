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
import type { InputMethod, ServiceInfo } from "@/lib/types";
import { useVoiceActivation } from "@/stores/use-voice-activation";

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
  voiceAutoSend: boolean;

  // Recording
  isRecording: boolean;
  liveTranscript: string;
  voiceError: string | null;

  // TTS
  isSpeaking: boolean;

  // Actions
  toggleVoice: () => void;
  prefetch: (text: string) => void;
  speak: (text: string) => void;
  stopSpeech: () => void;
  registerChatCallbacks: (
    send: (text: string, inputMethod?: InputMethod) => void,
    draft: (text: string) => void,
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
let draftCallback: ((text: string) => void) | null = null;
let idleTimer: ReturnType<typeof setTimeout> | null = null;
let ttsAbort: AbortController | null = null;
let ttsQueue: string[] = [];
let ttsProcessing = false;
// Bumped by stopSpeech to invalidate an in-flight processQueue loop, so a
// stop-then-speak sequence never leaves two loops draining ttsQueue at once.
let ttsEpoch = 0;
// Prepared TTS ids, warmed during the typing-pacing delay so playback can
// start the streamed GET immediately when the message is shown.
const ttsPrefetchCache = new Map<string, Promise<string>>();

function clearIdleTimer() {
  if (idleTimer) {
    clearTimeout(idleTimer);
    idleTimer = null;
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
  const voiceAutoSend = boolSetting(stt, "auto_send", true);
  return { sttAvailable, speechEnabled, voiceAutoSend };
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
    voiceAutoSend: true,

    isRecording: false,
    liveTranscript: "",
    voiceError: null,

    isSpeaking: false,

    toggleVoice: () => {
      if (transcriber?.isActive()) {
        const isHold = useVoiceActivation.getState().mode === "hold";
        const captured = isHold ? get().liveTranscript.trim() : "";
        transcriber.stop();
        transcriber = null;
        clearIdleTimer();
        set({ isRecording: false, liveTranscript: "" });
        if (captured) sendCallback?.(captured, "voice");
        return;
      }

      const { sttAvailable, agentName } = get();
      if (!sttAvailable || !agentName) {
        set({
          voiceError: "Voice input not configured — ask the agent to set it up",
        });
        return;
      }

      set({ voiceError: null });

      // Stop TTS when recording starts
      get().stopSpeech();

      const isHold = useVoiceActivation.getState().mode === "hold";
      const idleTimeoutMs = useVoiceActivation.getState().toggleIdleTimeoutMs;

      const armIdleTimer = () => {
        if (isHold || !idleTimeoutMs) return;
        clearIdleTimer();
        idleTimer = setTimeout(() => {
          idleTimer = null;
          if (transcriber?.isActive()) get().toggleVoice();
        }, idleTimeoutMs);
      };

      const stream = new Transcriber({
        agentName,
        accumulate: isHold,
        onTranscript: (text) => {
          set({ liveTranscript: text });
          if (!isHold && !get().voiceAutoSend) draftCallback?.(text);
          if (text) armIdleTimer();
        },
        onTurnEnd: (text) => {
          if (isHold) return;
          if (get().voiceAutoSend) sendCallback?.(text, "voice");
          else draftCallback?.(text);
          set({ liveTranscript: "" });
          armIdleTimer();
        },
        onTurnStart: () => {
          if (boolSetting(get().sttStatus, "interrupt_tts", true))
            get().stopSpeech();
        },
        onError: (err) => {
          set({ voiceError: err, isRecording: false });
          transcriber?.stop();
          transcriber = null;
        },
      });

      transcriber = stream;
      stream
        .start()
        .then(() => {
          set({ isRecording: true });
          armIdleTimer();
        })
        .catch((err: unknown) => {
          const msg =
            err instanceof Error ? err.message : "Microphone access denied";
          set({ voiceError: msg });
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

    registerChatCallbacks: (send, draft) => {
      sendCallback = send;
      draftCallback = draft;
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
      transcriber?.stop();
      transcriber = null;
      get().stopSpeech();
      set({ isRecording: false, liveTranscript: "" });
    },
  };
});
