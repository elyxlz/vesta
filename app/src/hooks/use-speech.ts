import { useCallback, useRef, useState } from "react";
import { streamSpeech } from "@/lib/voice";

export function useSpeech(agentName: string | null, speechEnabled: boolean) {
  const [isSpeaking, setIsSpeaking] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const queueRef = useRef<string[]>([]);
  const playingRef = useRef(false);
  const speechEnabledRef = useRef(speechEnabled);
  speechEnabledRef.current = speechEnabled;

  const processQueue = useCallback(async () => {
    if (playingRef.current || queueRef.current.length === 0 || !agentName) return;
    playingRef.current = true;
    setIsSpeaking(true);

    while (queueRef.current.length > 0) {
      const text = queueRef.current.shift()!;
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        await streamSpeech(text, agentName, controller.signal);
      } catch (err) {
        if (!controller.signal.aborted) {
          console.warn("[tts] playback failed:", err);
        }
      }
      abortRef.current = null;
    }

    playingRef.current = false;
    setIsSpeaking(false);
  }, [agentName]);

  const speak = useCallback((text: string) => {
    if (!speechEnabledRef.current) {
      console.debug("[tts] skipped — speechEnabled=false");
      return;
    }
    if (!agentName) return;
    console.debug("[tts] queueing:", text.slice(0, 60));
    queueRef.current.push(text);
    processQueue();
  }, [processQueue, agentName]);

  const stop = useCallback(() => {
    queueRef.current = [];
    abortRef.current?.abort();
  }, []);

  return { isSpeaking, speak, stop };
}
