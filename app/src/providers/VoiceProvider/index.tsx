import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import { useVoiceStatus } from "./use-voice-status";
import { useVoiceInput } from "./use-voice-input";
import { useVoiceOutput } from "./use-voice-output";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import type { SttStatus, TtsStatus } from "@/lib/voice";

interface VoiceContextValue {
  sttStatus: SttStatus | null;
  ttsStatus: TtsStatus | null;
  sttAvailable: boolean;
  speechEnabled: boolean;
  voiceAutoSend: boolean;

  patchStt: (patch: Partial<SttStatus>) => void;
  patchTts: (patch: Partial<TtsStatus>) => void;
  refreshVoiceStatus: () => void;

  isRecording: boolean;
  liveTranscript: string;
  toggleVoice: () => void;
  voiceError: string | null;

  isSpeaking: boolean;
  speak: (text: string) => void;
  stopSpeech: () => void;

  registerChatCallbacks: (
    send: (text: string) => void,
    draft: (text: string) => void,
  ) => void;
}

const VoiceContext = createContext<VoiceContextValue | null>(null);

export function VoiceProvider({ children }: { children: ReactNode }) {
  const { name: agentName } = useSelectedAgent();
  const sendRef = useRef<((text: string) => void) | null>(null);
  const draftRef = useRef<((text: string) => void) | null>(null);

  const onSend = useCallback((text: string) => {
    sendRef.current?.(text);
  }, []);
  const onDraft = useCallback((text: string) => {
    draftRef.current?.(text);
  }, []);
  const registerChatCallbacks = useCallback(
    (send: (text: string) => void, draft: (text: string) => void) => {
      sendRef.current = send;
      draftRef.current = draft;
    },
    [],
  );

  const {
    stt: sttStatus,
    tts: ttsStatus,
    refresh: refreshVoiceStatus,
    patchStt,
    patchTts,
  } = useVoiceStatus(agentName || null);

  const sttAvailable = (sttStatus?.configured && sttStatus?.enabled) ?? false;
  const speechEnabled = (ttsStatus?.configured && ttsStatus?.enabled) ?? false;
  const voiceAutoSend =
    (sttStatus?.settings?.find((s) => s.key === "auto_send")
      ?.value as boolean) ?? true;

  const {
    isSpeaking,
    speak,
    stop: stopSpeech,
  } = useVoiceOutput(agentName || null, speechEnabled);

  const onRecordingStart = useCallback(() => {
    stopSpeech();
  }, [stopSpeech]);

  const {
    isRecording,
    liveTranscript,
    toggle: toggleVoice,
    error: voiceError,
  } = useVoiceInput({
    agentName: agentName || "",
    onSend,
    onDraft,
    onRecordingStart,
    sttAvailable,
    voiceAutoSend,
  });

  const value = useMemo<VoiceContextValue>(
    () => ({
      sttStatus,
      ttsStatus,
      sttAvailable,
      speechEnabled,
      voiceAutoSend,
      patchStt,
      patchTts,
      refreshVoiceStatus,
      isRecording,
      liveTranscript,
      toggleVoice,
      voiceError,
      isSpeaking,
      speak,
      stopSpeech,
      registerChatCallbacks,
    }),
    [
      sttStatus,
      ttsStatus,
      sttAvailable,
      speechEnabled,
      voiceAutoSend,
      patchStt,
      patchTts,
      refreshVoiceStatus,
      isRecording,
      liveTranscript,
      toggleVoice,
      voiceError,
      isSpeaking,
      speak,
      stopSpeech,
      registerChatCallbacks,
    ],
  );

  return (
    <VoiceContext.Provider value={value}>{children}</VoiceContext.Provider>
  );
}

export function useVoice() {
  const context = useContext(VoiceContext);
  if (!context) {
    throw new Error("useVoice must be used within VoiceProvider");
  }
  return context;
}
