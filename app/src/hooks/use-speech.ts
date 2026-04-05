import { useCallback, useRef, useState } from "react";
import { streamSpeech } from "@/lib/elevenlabs";
import { useSettings } from "@/stores/use-settings";

export function useSpeech() {
  const [isSpeaking, setIsSpeaking] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const queueRef = useRef<string[]>([]);
  const playingRef = useRef(false);

  const processQueue = useCallback(async () => {
    if (playingRef.current || queueRef.current.length === 0) return;
    playingRef.current = true;
    setIsSpeaking(true);

    while (queueRef.current.length > 0) {
      const text = queueRef.current.shift()!;
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        await streamSpeech(text, controller.signal);
      } catch (err) {
        if (!controller.signal.aborted) {
          console.warn("[tts] playback failed:", err);
        }
      }
      abortRef.current = null;
    }

    playingRef.current = false;
    setIsSpeaking(false);
  }, []);

  const speak = useCallback((text: string) => {
    if (!useSettings.getState().speechEnabled) {
      console.debug("[tts] skipped — speechEnabled=false");
      return;
    }
    console.debug("[tts] queueing:", text.slice(0, 60));
    queueRef.current.push(text);
    processQueue();
  }, [processQueue]);

  const stop = useCallback(() => {
    queueRef.current = [];
    abortRef.current?.abort();
  }, []);

  return { isSpeaking, speak, stop };
}
