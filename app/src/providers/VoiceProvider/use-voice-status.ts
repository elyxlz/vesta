import { useCallback, useEffect, useState } from "react";
import { fetchSttStatus, fetchTtsStatus, type SttStatus, type TtsStatus } from "@/lib/voice";

const REFRESH_INTERVAL_MS = 10_000;

export function useVoiceStatus(agentName: string | null) {
  const [stt, setStt] = useState<SttStatus | null>(null);
  const [tts, setTts] = useState<TtsStatus | null>(null);
  const [version, setVersion] = useState(0);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!agentName) {
      setStt(null);
      setTts(null);
      return;
    }
    const ctrl = new AbortController();
    Promise.all([
      fetchSttStatus(agentName, ctrl.signal),
      fetchTtsStatus(agentName, ctrl.signal),
    ])
      .then(([s, t]) => {
        if (ctrl.signal.aborted) return;
        setStt((prev) => (prev && same(prev, s) ? prev : s));
        setTts((prev) => (prev && same(prev, t) ? prev : t));
      })
      .catch(() => {});
    return () => ctrl.abort();
  }, [agentName, version]);

  useEffect(() => {
    if (!agentName) return;
    const interval = setInterval(refresh, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [agentName, refresh]);

  const patchStt = useCallback((patch: Partial<SttStatus>) => {
    setStt((prev) => prev ? { ...prev, ...patch } : prev);
  }, []);

  const patchTts = useCallback((patch: Partial<TtsStatus>) => {
    setTts((prev) => prev ? { ...prev, ...patch } : prev);
  }, []);

  return { stt, tts, refresh, patchStt, patchTts };
}

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
