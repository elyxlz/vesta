import { useCallback, useEffect, useState } from "react";
import {
  fetchSttStatus,
  fetchTtsStatus,
  type SttStatus,
  type TtsStatus,
} from "@/lib/voice";
import type { ServiceInfo } from "@/lib/types";

export function useVoiceStatus(
  agentName: string | null,
  services: Record<string, ServiceInfo>,
  voiceRev?: number,
) {
  const [stt, setStt] = useState<SttStatus | null>(null);
  const [tts, setTts] = useState<TtsStatus | null>(null);

  const hasVoice = "voice" in (services ?? {});

  const refresh = useCallback(() => {
    if (!agentName) return;
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
  }, [agentName]);

  useEffect(() => {
    if (!agentName) {
      setStt(null);
      setTts(null);
      return;
    }
    if (!hasVoice) {
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
  }, [agentName, hasVoice, voiceRev]);

  const patchStt = useCallback((patch: Partial<SttStatus>) => {
    setStt((prev) => (prev ? { ...prev, ...patch } : prev));
  }, []);

  const patchTts = useCallback((patch: Partial<TtsStatus>) => {
    setTts((prev) => (prev ? { ...prev, ...patch } : prev));
  }, []);

  return { stt, tts, refresh, patchStt, patchTts };
}

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
