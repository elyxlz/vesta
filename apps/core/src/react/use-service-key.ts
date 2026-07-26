import { useEffect, useState } from "react"

import type { ServiceKeyCache } from "../service-keys/service-keys"

interface ServiceKeyState {
  key: string | null
  error: unknown
}

// Resolve the service key for one agent and service. The result is derived from the pair it
// was minted for, never reset, so a key that arrives for a previous agent or service is
// dropped rather than briefly rendered and a frame can never load carrying the wrong
// credential.
export function useServiceKey(
  cache: ServiceKeyCache | null,
  agent: string,
  service: string,
  enabled: boolean,
): ServiceKeyState {
  const [resolved, setResolved] = useState<{
    agent: string
    service: string
    key: string
  } | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (!enabled || !cache) return
    let cancelled = false
    setError(null)
    void cache
      .get(agent, service)
      .then((key) => {
        if (!cancelled) setResolved({ agent, service, key })
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason)
      })
    return () => {
      cancelled = true
    }
  }, [agent, cache, enabled, service])

  const isRequestedPair =
    resolved !== null && resolved.agent === agent && resolved.service === service
  return { key: isRequestedPair ? resolved.key : null, error }
}
