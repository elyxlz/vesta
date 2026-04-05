import { useCallback, useEffect, useRef, useState } from "react";
import { DeepgramStream } from "@/lib/deepgram";
import { useSettings } from "@/stores/use-settings";

interface VoiceInputCallbacks {
  onSend: (text: string) => void;
  onDraft: (text: string) => void;
}

export function useVoiceInput({ onSend, onDraft }: VoiceInputCallbacks) {
  const voiceAutoSend = useSettings((s) => s.voiceAutoSend);
  const sttEotThreshold = useSettings((s) => s.sttEotThreshold);
  const sttEotTimeoutMs = useSettings((s) => s.sttEotTimeoutMs);
  const [isRecording, setIsRecording] = useState(false);
  const [liveTranscript, setLiveTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<DeepgramStream | null>(null);

  const toggle = useCallback(() => {
    if (streamRef.current?.isActive()) {
      streamRef.current.stop();
      streamRef.current = null;
      setIsRecording(false);
      setLiveTranscript("");
      return;
    }

    setError(null);
    const stream = new DeepgramStream({
      eotThreshold: sttEotThreshold,
      eotTimeoutMs: sttEotTimeoutMs,
      onTranscript: (text) => {
        setLiveTranscript(text);
        if (!voiceAutoSend) {
          onDraft(text);
        }
      },
      onTurnEnd: (text) => {
        if (voiceAutoSend) {
          onSend(text);
        } else {
          onDraft(text);
        }
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
  }, [onSend, onDraft, voiceAutoSend, sttEotThreshold, sttEotTimeoutMs]);

  useEffect(() => {
    if (!error) return;
    const timer = setTimeout(() => setError(null), 5000);
    return () => clearTimeout(timer);
  }, [error]);

  return { isRecording, liveTranscript, toggle, error };
}
