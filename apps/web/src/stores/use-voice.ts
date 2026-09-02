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
  // Voice has been set up at all (either service configured), the gate for showing the
  // composer's voice buttons; being configured but off is a per-click toast, not a hide.
  voiceConfigured: boolean;

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
  // Microphone mute inside a conversation: silence flows instead of speech, so the session
  // (and any live turn's endpointing) stays up while nothing the user says gets through.
  micMuted: boolean;
  // End a silent conversation on its own after the inactivity window (on by default).
  conversationAutoEnd: boolean;
  // A conversation yields the floor: replies are held off the speaker while you talk, and the
  // agent is told you are speaking so it waits for your whole thought (on by default).
  conversationYield: boolean;

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
  toggleMicMuted: () => void;
  setConversationAutoEnd: (value: boolean) => void;
  setConversationYield: (value: boolean) => void;
  // The chat's send, its input reset (a voice mode takes the composer over, so typed text is
  // dropped when one starts), and the chat socket's speaking report for a yielding conversation.
  registerChat: (
    send: (text: string, inputMethod?: InputMethod) => void,
    clearInput: () => void,
    reportSpeaking: (speaking: boolean) => void,
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
let reportSpeakingCallback: ((speaking: boolean) => void) | null = null;

const MUTE_STORAGE_KEY = "voice-muted";
const AUTO_END_STORAGE_KEY = "voice-conversation-auto-end";
const YIELD_STORAGE_KEY = "voice-conversation-yield";
function loadStoredFlag(key: string, fallback: boolean): boolean {
  if (typeof localStorage === "undefined") return fallback;
  const raw = localStorage.getItem(key);
  return raw === null ? fallback : raw === "1";
}

function boolSetting(
  status: SttStatus | null,
  key: string,
  fallback: boolean,
): boolean {
  const value = status?.settings?.find((s) => s.key === key)?.value;
  return typeof value === "boolean" ? value : fallback;
}

function deriveStatus(stt: SttStatus | null, tts: TtsStatus | null) {
  const sttAvailable = (stt?.configured && stt.enabled) ?? false;
  const speechEnabled = (tts?.configured && tts.enabled) ?? false;
  const voiceConfigured =
    (stt?.configured ?? false) || (tts?.configured ?? false);
  return { sttAvailable, speechEnabled, voiceConfigured };
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
      capture: browserCapture(() => get().micMuted),
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
          ...(mode === null
            ? { listening: false, liveTranscript: "", micMuted: false }
            : {}),
        }),
      onListeningChange: (listening) => set({ listening }),
      onSpeakingChange: (isSpeaking) => set({ isSpeaking }),
      onUserSpeakingChange: (speaking) => reportSpeakingCallback?.(speaking),
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
      inactivityMs: get().conversationAutoEnd ? CONVERSATION_INACTIVITY_MS : 0,
      yieldToUser: get().conversationYield,
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
    voiceConfigured: false,

    recordingMode: null,
    micMuted: false,
    conversationAutoEnd: loadStoredFlag(AUTO_END_STORAGE_KEY, true),
    conversationYield: loadStoredFlag(YIELD_STORAGE_KEY, true),
    listening: false,
    liveTranscript: "",
    voiceError: null,

    isSpeaking: false,
    muted: loadStoredFlag(MUTE_STORAGE_KEY, false),

    startVoice: (mode) => {
      if (session.mode() !== null) return;
      const { sttAvailable, speechEnabled, agentName, sttStatus, ttsStatus } =
        get();
      if (!agentName) return;
      // The voice buttons always show; a mode the settings do not allow points the user at the
      // fix (set up, or enable) with a toast rather than starting a silent or dead session.
      if (!sttAvailable) {
        useToastStore
          .getState()
          .show(
            "error",
            sttStatus?.configured
              ? "enable speech-to-text in the settings"
              : "set up speech-to-text in the settings",
          );
        return;
      }
      // A conversation speaks back, so it also needs text-to-speech ready.
      if (mode === "conversation" && !speechEnabled) {
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
    toggleMicMuted: () => {
      set({ micMuted: !get().micMuted });
    },
    setConversationAutoEnd: (value) => {
      if (typeof localStorage !== "undefined")
        localStorage.setItem(AUTO_END_STORAGE_KEY, value ? "1" : "0");
      set({ conversationAutoEnd: value });
    },
    setConversationYield: (value) => {
      if (typeof localStorage !== "undefined")
        localStorage.setItem(YIELD_STORAGE_KEY, value ? "1" : "0");
      set({ conversationYield: value });
    },
    toggleMuted: () => {
      const next = !get().muted;
      if (typeof localStorage !== "undefined")
        localStorage.setItem(MUTE_STORAGE_KEY, next ? "1" : "0");
      if (next) session.stopSpeech();
      set({ muted: next });
    },

    registerChat: (send, clearInput, reportSpeaking) => {
      sendCallback = send;
      clearInputCallback = clearInput;
      reportSpeakingCallback = reportSpeaking;
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
      // A live session is pinned to the agent it started with; past a switch the module-level
      // chat callbacks belong to the new agent, so a surviving session would route its sends
      // and speaking reports to the wrong daemon. The switch ends the session instead.
      if (name !== get().agentName && session.mode() !== null) session.cancel();
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
