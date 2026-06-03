import { useCallback, useEffect, useState } from "react";
import { getProvider, type ProviderInfo } from "@/api/agents";

/// Fetch an agent's current provider (kind + model). Shared by the settings
/// model switcher and the agent island's read-only model line. Pass `revalidate`
/// (e.g. the agent's status) to refetch when it changes — that's how the card
/// picks up a provider switch, which restarts the agent.
export function useProvider(name: string | null, revalidate?: unknown) {
  const [provider, setProvider] = useState<ProviderInfo | null>(null);

  const refresh = useCallback(() => {
    if (!name) return;
    getProvider(name)
      .then(setProvider)
      .catch(() => setProvider(null));
  }, [name]);

  useEffect(() => {
    refresh();
  }, [refresh, revalidate]);

  return { provider, refresh };
}
