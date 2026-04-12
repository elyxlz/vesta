import { useCallback, useEffect, useRef, useState } from "react";
import { Transcriber } from "@/lib/voice";

interface VoiceInputCallbacks {
  agentName: string;
  onSend: (text: string) => void;
  onDraft: (text: string) => void;
  onRecordingStart?: () => void;
  onTurnStart?: () => void;
  sttAvailable: boolean;
  voiceAutoSend: boolean;
}

export function useVoiceInput({
  agentName,
  onSend,
  onDraft,
  onRecordingStart,
  onTurnStart,
  sttAvailable,
  voiceAutoSend,
}: VoiceInputCallbacks) {
  const [isRecording, setIsRecording] = useState(false);
  const [liveTranscript, setLiveTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<Transcriber | null>(null);
  const onSendRef = useRef(onSend);
  const onDraftRef = useRef(onDraft);
  const onTurnStartRef = useRef(onTurnStart);
  const autoSendRef = useRef(voiceAutoSend);
  onSendRef.current = onSend;
  onDraftRef.current = onDraft;
  onTurnStartRef.current = onTurnStart;
  autoSendRef.current = voiceAutoSend;

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
    onRecordingStart?.();
    const stream = new Transcriber({
      agentName,
      onTranscript: (text) => {
        setLiveTranscript(text);
        if (!autoSendRef.current) onDraftRef.current(text);
      },
      onTurnEnd: (text) => {
        if (autoSendRef.current) onSendRef.current(text);
        else onDraftRef.current(text);
        setLiveTranscript("");
      },
      onTurnStart: () => onTurnStartRef.current?.(),
      onError: (err) => {
        setError(err);
        setIsRecording(false);
        streamRef.current?.stop();
        streamRef.current = null;
      },
    });

    streamRef.current = stream;
    stream
      .start()
      .then(() => {
        setIsRecording(true);
      })
      .catch((err) => {
        const msg =
          err instanceof Error ? err.message : "Microphone access denied";
        setError(msg);
        streamRef.current = null;
      });
  }, [agentName, onRecordingStart, sttAvailable]);

  useEffect(() => {
    return () => {
      streamRef.current?.stop();
      streamRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!error) return;
    const timer = setTimeout(() => setError(null), 5000);
    return () => clearTimeout(timer);
  }, [error]);

  return { isRecording, liveTranscript, toggle, error };
}
