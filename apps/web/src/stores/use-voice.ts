import { create } from "zustand";
import {
  createVoiceSession,
  type InputMethod,
  type ServiceInfo,
  type VoiceMode,
  type VoiceSession,
} from "@vesta/core";
import {
  browserCapture,
  browserPlayer,
  browserSocket,
  prepareSpeech,
  voiceWsUrl,
  fetchSttStatus,
  fetchTtsStatus,
  type SttStatus,
  type TtsStatus,
} from "@/lib/voice";
import { useToastStore } from "@/stores/use-toast";

export type { VoiceMode };

// A conversation with no user turn for this long ends itself, since an open transcription
// stream costs by the minute; the user is told through a toast.
const CONVERSATION_INACTIVITY_MINUTES = 15;
export const CONVERSATION_INACTIVITY_MS =
  CONVERSATION_INACTIVITY_MINUTES * 60_000;

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

  // Recording (set at press time so a release that beats the microphone still lands).
  recordingMode: VoiceMode | null;
  // True once the microphone and the transcription socket are up.
  listening: boolean;
  liveTranscript: string;
  voiceError: string | null;

  // TTS
  isSpeaking: boolean;
  // A per-device mute of spoken replies. A conversation speaks regardless; this silences the
  // ambient read-aloud of replies outside one.
  muted: boolean;

  // Actions
  startVoice: (mode: VoiceMode) => void;
  // Confirms a dictation (sends what it captured) or ends a conversation.
  stopVoice: () => void;
  // Ends either mode and drops anything captured.
  cancelVoice: () => void;
  prefetch: (text: string) => void;
  speak: (text: string) => void;
  stopSpeech: () => void;
  toggleMuted: () => void;
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

// The chat callbacks and the composed session live outside React, since the store is a
// singleton and the session owns the microphone and speaker for the tab's lifetime.
let sendCallback: ((text: string, inputMethod?: InputMethod) => void) | null =
  null;
let clearInputCallback: (() => void) | null = null;

const MUTE_STORAGE_KEY = "voice-muted";
function loadMuted(): boolean {
  if (typeof localStorage === "undefined") return false;
  return localStorage.getItem(MUTE_STORAGE_KEY) === "1";
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

// A reply is spoken when text-to-speech is available and either a conversation is running (it
// always speaks) or the user has not muted the ambient read-aloud.
function speakable(state: {
  speechEnabled: boolean;
  muted: boolean;
  recordingMode: VoiceMode | null;
}): boolean {
  if (!state.speechEnabled) return false;
  return state.recordingMode === "conversation" || !state.muted;
}

export const useVoice = create<VoiceState>((set, get) => {
  const session: VoiceSession = createVoiceSession(
    {
      buildUrl: () => voiceWsUrl(get().agentName ?? ""),
      createSocket: browserSocket,
      capture: browserCapture(),
      player: browserPlayer(() => get().agentName),
      setTimer: (fn, ms) => setTimeout(fn, ms),
      clearTimer: (handle) => clearTimeout(handle),
    },
    {
      onTranscript: (text) => set({ liveTranscript: text }),
      onSend: (text) => sendCallback?.(text, "voice"),
      onError: (message) => set({ voiceError: message }),
      onModeChange: (mode) =>
        set({
          recordingMode: mode,
          ...(mode === null ? { listening: false, liveTranscript: "" } : {}),
        }),
      onListeningChange: (listening) => set({ listening }),
      onSpeakingChange: (isSpeaking) => set({ isSpeaking }),
      onInactivityStop: () =>
        useToastStore
          .getState()
          .show(
            "info",
            `conversation ended after ${String(CONVERSATION_INACTIVITY_MINUTES)} minutes of silence`,
          ),
    },
    () => ({
      interruptTts: boolSetting(get().sttStatus, "interrupt_tts", true),
      inactivityMs: CONVERSATION_INACTIVITY_MS,
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

    recordingMode: null,
    listening: false,
    liveTranscript: "",
    voiceError: null,

    isSpeaking: false,
    muted: loadMuted(),

    startVoice: (mode) => {
      if (session.mode() !== null) return;
      const { sttAvailable, agentName, ttsStatus } = get();
      if (!sttAvailable || !agentName) {
        set({
          voiceError: "Voice input not configured — ask the agent to set it up",
        });
        return;
      }
      // A conversation speaks back, so it needs text-to-speech ready. Point the user at the
      // fix (set up, or enable) rather than starting a session that stays silent.
      if (mode === "conversation" && !get().speechEnabled) {
        useToastStore
          .getState()
          .show(
            "error",
            ttsStatus?.configured
              ? "enable text-to-speech in the settings"
              : "set up text-to-speech in the settings",
          );
        return;
      }
      set({ voiceError: null });
      clearInputCallback?.();
      session.start(mode).catch((err: unknown) => {
        set({
          voiceError:
            err instanceof Error ? err.message : "Microphone access denied",
        });
      });
    },

    stopVoice: () => session.stop(),
    cancelVoice: () => session.cancel(),

    prefetch: (text) => {
      if (!speakable(get())) return;
      session.prefetch(text);
    },
    speak: (text) => {
      if (!speakable(get())) return;
      session.speak(text);
    },
    stopSpeech: () => session.stopSpeech(),
    toggleMuted: () => {
      const next = !get().muted;
      if (typeof localStorage !== "undefined")
        localStorage.setItem(MUTE_STORAGE_KEY, next ? "1" : "0");
      if (next) session.stopSpeech();
      set({ muted: next });
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
          set({ sttStatus: stt, ttsStatus: tts, ...deriveStatus(stt, tts) });
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
      session.cancel();
      session.stopSpeech();
    },
  };
});

export { prepareSpeech };
