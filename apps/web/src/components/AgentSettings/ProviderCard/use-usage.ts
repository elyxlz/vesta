import { useCallback, useEffect, useState } from "react";
import { fetchUsage, type Usage } from "@/api/agents";

/// Fetch an agent's normalized plan usage (the agent's GET /provider/usage). Local to ProviderCard,
/// its only consumer — mirrors the use-provider hook rather than a global store.
export function useUsage(name: string | null) {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  const refresh = useCallback(() => {
    if (!name) return;
    setLoading(true);
    setError(false);
    fetchUsage(name)
      .then(setUsage)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [name]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { usage, loading, error, refresh };
}
