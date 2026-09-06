import { useEffect, useState } from "react";
import type { VoiceMode, VoiceStatus } from "@vesta/core";
import { visualSwitch } from "./launch-query";

// visualConversation=listening|speaking|muted holds the chat in a live conversation with a fixed
// transcript, so the panel captures without a microphone or a speech service. Absent, the hook
// is idle and the composer renders as in production.
const conversation = visualSwitch("visualConversation");
const TRANSCRIPT = "Also book the room for Thursday";

interface LiveVoiceOptions {
  name: string;
  enabled: boolean;
  sttStatus: VoiceStatus | null;
  onTranscript: (text: string) => void;
  onSend: (text: string) => void;
  onError: (message: string) => void;
  onInactivityStop: () => void;
  onUserSpeakingChange: (speaking: boolean) => void;
}

export function useLiveVoice({ onTranscript }: LiveVoiceOptions) {
  const recordingMode: VoiceMode | null =
    conversation === null ? null : "conversation";
  const [micMuted, setMicMuted] = useState(conversation === "muted");

  useEffect(() => {
    if (conversation !== null) onTranscript(TRANSCRIPT);
  }, [onTranscript]);

  return {
    recordingMode,
    listening: conversation !== null,
    speaking: conversation === "speaking",
    ttsEnabled: true,
    micMuted,
    toggleMicMuted: () => setMicMuted((muted) => !muted),
    start: async (_mode: VoiceMode) => undefined,
    stop: () => undefined,
    cancel: () => undefined,
    speak: (_text: string) => undefined,
    prefetch: (_text: string) => undefined,
    stopSpeech: () => undefined,
  };
}
