import { useCallback, useEffect, useRef, useState } from "react";
import { Transcriber } from "@/lib/voice";
import { useVoiceStatus } from "@/hooks/use-voice-status";
import { useSettings } from "@/stores/use-settings";

interface VoiceInputCallbacks {
  agentName: string;
  onSend: (text: string) => void;
  onDraft: (text: string) => void;
}

export function useVoiceInput({ agentName, onSend, onDraft }: VoiceInputCallbacks) {
  const voiceAutoSend = useSettings((s) => s.voiceAutoSend);
  const { status } = useVoiceStatus(agentName);
  const sttAvailable = status?.stt.configured ?? false;
  const [isRecording, setIsRecording] = useState(false);
  const [liveTranscript, setLiveTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<Transcriber | null>(null);

  const toggle = useCallback(() => {
    if (streamRef.current?.isActive()) {
      streamRef.current.stop();
      streamRef.current = null;
      setIsRecording(false);
      setLiveTranscript("");
      return;
    }

    if (!sttAvailable) {
      setError("Voice input not configured — ask the agent to set it up");
      return;
    }

    setError(null);
    const stream = new Transcriber({
      agentName,
      onTranscript: (text) => {
        setLiveTranscript(text);
        if (!voiceAutoSend) onDraft(text);
      },
      onTurnEnd: (text) => {
        if (voiceAutoSend) onSend(text);
        else onDraft(text);
        setLiveTranscript("");
      },
      onTurnStart: () => {},
      onError: (err) => {
        setError(err);
        setIsRecording(false);
        streamRef.current?.stop();
        streamRef.current = null;
      },
    });

    streamRef.current = stream;
    stream.start().then(() => {
      setIsRecording(true);
    }).catch((err) => {
      const msg = err instanceof Error ? err.message : "Microphone access denied";
      setError(msg);
      streamRef.current = null;
    });
  }, [agentName, onSend, onDraft, voiceAutoSend, sttAvailable]);

  useEffect(() => {
    if (!error) return;
    const timer = setTimeout(() => setError(null), 5000);
    return () => clearTimeout(timer);
  }, [error]);

  return { isRecording, liveTranscript, toggle, error, sttAvailable };
}
