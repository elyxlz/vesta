import { useCallback, useEffect, useState } from "react";
import { fetchVoiceStatus, type VoiceStatus } from "@/lib/voice";

const REFRESH_INTERVAL_MS = 10_000;

export function useVoiceStatus(agentName: string | null) {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!agentName) {
      setStatus(null);
      setError(null);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    fetchVoiceStatus(agentName, ctrl.signal)
      .then((s) => {
        if (ctrl.signal.aborted) return;
        // Skip update if the shape matches what we already have — polling
        // otherwise rerenders every 10s with an identical object.
        setStatus((prev) => (prev && sameStatus(prev, s) ? prev : s));
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setError(err instanceof Error ? err.message : "Failed to load voice status");
      })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
  }, [agentName, version]);

  useEffect(() => {
    if (!agentName) return;
    const interval = setInterval(refresh, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [agentName, refresh]);

  return { status, loading, error, refresh };
}

function sameStatus(a: VoiceStatus, b: VoiceStatus): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
