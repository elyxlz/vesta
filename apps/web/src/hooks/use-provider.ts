import { useCallback, useEffect, useState } from "react";
import { getProvider, type ProviderInfo } from "@/api/agents";

/// Fetch an agent's current provider (kind + model). Shared by the settings
/// model switcher and the agent island's read-only model line.
export function useProvider(name: string | null) {
  const [provider, setProvider] = useState<ProviderInfo | null>(null);

  const refresh = useCallback(() => {
    if (!name) return;
    getProvider(name)
      .then(setProvider)
      .catch(() => setProvider(null));
  }, [name]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { provider, refresh };
}
