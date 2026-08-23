import { create } from "zustand";
import {
  createVoiceSession,
  voiceBoolSetting,
  voiceDomainReady,
  type InputMethod,
  type ServiceInfo,
} from "@vesta/core";
import {
  buildListenUrl,
  createMicCapture,
  createVoiceSocket,
  fetchSttStatus,
  fetchTtsStatus,
  prepareSpeech,
  streamPreparedSpeech,
  type SttStatus,
  type TtsStatus,
} from "@/lib/voice";
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
let sendCallback: ((text: string, inputMethod?: InputMethod) => void) | null =
  null;
let draftCallback: ((text: string) => void) | null = null;

function deriveStatus(stt: SttStatus | null, tts: TtsStatus | null) {
  return {
    sttAvailable: voiceDomainReady(stt),
    speechEnabled: voiceDomainReady(tts),
    voiceAutoSend: voiceBoolSetting(stt, "auto_send", true),
  };
}

export const useVoice = create<VoiceState>((set, get) => {
  // The behavior model (barge-in, auto-send routing, hold accumulation, the
  // TTS queue) is @vesta/core's voice session; this store adapts the browser
  // ports and projects the session's state for React.
  const session = createVoiceSession(
    {
      buildUrl: () => {
        const { agentName } = get();
        return agentName
          ? buildListenUrl(agentName)
          : Promise.reject(new Error("no agent selected"));
      },
      createSocket: createVoiceSocket,
      capture: createMicCapture(),
      player: {
        prepare: (text) => {
          const { agentName } = get();
          return agentName
            ? prepareSpeech(text, agentName)
            : Promise.reject(new Error("no agent selected"));
        },
        play: (id, signal) => {
          const { agentName } = get();
          return agentName
            ? streamPreparedSpeech(id, agentName, signal)
            : Promise.resolve();
        },
      },
      setTimer: (fn, ms) => window.setTimeout(fn, ms),
      clearTimer: (handle) => window.clearTimeout(handle),
    },
    {
      onTranscript: (text) => set({ liveTranscript: text }),
      onSend: (text) => sendCallback?.(text, "voice"),
      onDraft: (text) => draftCallback?.(text),
      onError: (message) => set({ voiceError: message }),
      onListeningChange: (listening) =>
        set(
          listening
            ? { isRecording: true }
            : { isRecording: false, liveTranscript: "" },
        ),
      onSpeakingChange: (speaking) => set({ isSpeaking: speaking }),
    },
    () => ({
      autoSend: get().voiceAutoSend,
      interruptTts: voiceBoolSetting(get().sttStatus, "interrupt_tts", true),
      hold: useVoiceActivation.getState().mode === "hold",
      idleTimeoutMs: useVoiceActivation.getState().toggleIdleTimeoutMs ?? 0,
    }),
  );

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
      if (get().isRecording) {
        session.stopListening();
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
      session.startListening().catch((err: unknown) => {
        const msg =
          err instanceof Error ? err.message : "Microphone access denied";
        set({ voiceError: msg });
      });
    },

    prefetch: (text: string) => {
      const { speechEnabled, agentName } = get();
      if (!speechEnabled || !agentName) return;
      console.debug("[tts] prefetching:", text.slice(0, 60));
      session.prefetch(text);
    },

    speak: (text: string) => {
      const { speechEnabled, agentName } = get();
      if (!speechEnabled || !agentName) return;
      console.debug("[tts] queueing:", text.slice(0, 60));
      session.speak(text);
    },

    stopSpeech: () => {
      session.stopSpeech();
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
      session.stopListening();
      session.stopSpeech();
      set({ isRecording: false, liveTranscript: "" });
    },
  };
});
