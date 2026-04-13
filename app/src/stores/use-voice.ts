import { create } from "zustand";
import {
  Transcriber,
  streamSpeech,
  fetchSttStatus,
  fetchTtsStatus,
  type SttStatus,
  type TtsStatus,
} from "@/lib/voice";
import type { ServiceInfo } from "@/lib/types";

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
  speak: (text: string) => void;
  stopSpeech: () => void;
  registerChatCallbacks: (
    send: (text: string) => void,
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
let sendCallback: ((text: string) => void) | null = null;
let draftCallback: ((text: string) => void) | null = null;
let ttsAbort: AbortController | null = null;
let ttsQueue: string[] = [];
let ttsProcessing = false;

function deriveStatus(stt: SttStatus | null, tts: TtsStatus | null) {
  const sttAvailable = (stt?.configured && stt?.enabled) ?? false;
  const speechEnabled = (tts?.configured && tts?.enabled) ?? false;
  const voiceAutoSend =
    (stt?.settings?.find((s) => s.key === "auto_send")?.value as boolean) ??
    true;
  return { sttAvailable, speechEnabled, voiceAutoSend };
}

export const useVoice = create<VoiceState>((set, get) => {
  const processQueue = async () => {
    const { agentName } = get();
    if (ttsProcessing || !agentName) return;
    ttsProcessing = true;
    set({ isSpeaking: true });

    while (ttsQueue.length > 0) {
      const text = ttsQueue.shift()!;
      const controller = new AbortController();
      ttsAbort = controller;
      try {
        await streamSpeech(text, agentName, controller.signal);
      } catch (err) {
        if (!controller.signal.aborted) {
          console.warn("[tts] playback failed:", err);
        }
      }
      ttsAbort = null;
    }

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
        transcriber.stop();
        transcriber = null;
        set({ isRecording: false, liveTranscript: "" });
        return;
      }

      const { sttAvailable, agentName, voiceAutoSend } = get();
      if (!sttAvailable || !agentName) {
        set({
          voiceError:
            "Voice input not configured — ask the agent to set it up",
        });
        return;
      }

      set({ voiceError: null });

      // Stop TTS when recording starts
      get().stopSpeech();

      const stream = new Transcriber({
        agentName,
        onTranscript: (text) => {
          set({ liveTranscript: text });
          if (!get().voiceAutoSend) draftCallback?.(text);
        },
        onTurnEnd: (text) => {
          if (get().voiceAutoSend) sendCallback?.(text);
          else draftCallback?.(text);
          set({ liveTranscript: "" });
        },
        onTurnStart: () => {
          const interruptTts =
            (get().sttStatus?.settings?.find((s) => s.key === "interrupt_tts")
              ?.value as boolean) ?? true;
          if (interruptTts) get().stopSpeech();
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
        })
        .catch((err) => {
          const msg =
            err instanceof Error ? err.message : "Microphone access denied";
          set({ voiceError: msg });
          transcriber = null;
        });
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
      const ctrl = new AbortController();
      Promise.all([
        fetchSttStatus(agentName, ctrl.signal),
        fetchTtsStatus(agentName, ctrl.signal),
      ])
        .then(([stt, tts]) => {
          if (ctrl.signal.aborted) return;
          set({
            sttStatus: stt,
            ttsStatus: tts,
            ...deriveStatus(stt, tts),
          });
        })
        .catch(() => {});
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
      set({ isRecording: false, liveTranscript: "" });
    },
  };
});
