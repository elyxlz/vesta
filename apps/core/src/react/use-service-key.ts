import { useEffect, useState } from "react";

import type { ServiceKeyCache } from "../service-keys/service-keys";

interface ServiceKeyState {
  key: string | null;
  error: unknown;
}

// A mint fails when the gateway is briefly unreachable, so the hook keeps asking: nothing else
// retries, and a panel with no key has nothing to show until one arrives.
export const MINT_RETRY_DELAY_MS = 5000;

interface MintOutcome {
  agent: string;
  service: string;
  key: string | null;
  error: unknown;
}

// Resolve the service key for one agent and service. The outcome is keyed by the pair it was
// minted for and read only while that pair is the one requested, so a key or a failure that
// arrives for a previous agent or service is dropped rather than briefly rendered and a frame can
// never load carrying the wrong credential.
export function useServiceKey(
  cache: ServiceKeyCache | null,
  agent: string,
  service: string,
  enabled: boolean,
): ServiceKeyState {
  const [outcome, setOutcome] = useState<MintOutcome | null>(null);

  useEffect(() => {
    if (!enabled || !cache) return;
    let cancelled = false;
    let retry: ReturnType<typeof setTimeout> | null = null;
    const attempt = (): void => {
      void cache
        .get(agent, service)
        .then((key) => {
          if (cancelled) return;
          setOutcome({ agent, service, key, error: null });
        })
        .catch((reason: unknown) => {
          if (cancelled) return;
          setOutcome({ agent, service, key: null, error: reason });
          retry = setTimeout(attempt, MINT_RETRY_DELAY_MS);
        });
    };
    attempt();
    return () => {
      cancelled = true;
      if (retry) clearTimeout(retry);
    };
  }, [agent, cache, enabled, service]);

  const isRequestedPair =
    outcome !== null && outcome.agent === agent && outcome.service === service;
  if (!isRequestedPair) return { key: null, error: null };
  return { key: outcome.key, error: outcome.error };
}
