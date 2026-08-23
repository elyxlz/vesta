import { useCallback, useEffect, useRef } from "react";
import { triggerTranscriptHaptic } from "@/voice/recording-haptics";

const TRANSCRIPT_HAPTIC_INTERVAL_MS = 110;

export function useTranscriptWordHaptics() {
  const maximumWordCount = useRef(0);
  const lastHapticAt = useRef(0);
  const pendingHaptic = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancelPendingHaptic = useCallback(() => {
    if (pendingHaptic.current === null) return;
    clearTimeout(pendingHaptic.current);
    pendingHaptic.current = null;
  }, []);

  useEffect(() => cancelPendingHaptic, [cancelPendingHaptic]);

  return useCallback(
    (text: string) => {
      if (process.env.EXPO_OS !== "ios") return;
      const trimmed = text.trim();
      if (!trimmed) {
        maximumWordCount.current = 0;
        cancelPendingHaptic();
        return;
      }

      const wordCount = trimmed.split(/\s+/u).length;
      if (wordCount <= maximumWordCount.current) return;
      maximumWordCount.current = wordCount;

      const pulse = () => {
        pendingHaptic.current = null;
        lastHapticAt.current = Date.now();
        void triggerTranscriptHaptic().catch(() => undefined);
      };
      const remaining =
        TRANSCRIPT_HAPTIC_INTERVAL_MS - (Date.now() - lastHapticAt.current);
      if (remaining <= 0) {
        cancelPendingHaptic();
        pulse();
      } else if (pendingHaptic.current === null) {
        pendingHaptic.current = setTimeout(pulse, remaining);
      }
    },
    [cancelPendingHaptic],
  );
}
