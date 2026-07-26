import { useEffect, useState } from "react"

import type { ServiceKeyCache } from "../service-keys/service-keys"

interface ServiceKeyState {
  key: string | null
  error: unknown
}

// A mint fails when the gateway is briefly unreachable, so the hook keeps asking: nothing else
// retries, and a panel with no key has nothing to show until one arrives.
export const MINT_RETRY_DELAY_MS = 5000

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
    let retry: ReturnType<typeof setTimeout> | null = null
    const attempt = (): void => {
      void cache
        .get(agent, service)
        .then((key) => {
          if (cancelled) return
          setResolved({ agent, service, key })
          setError(null)
        })
        .catch((reason: unknown) => {
          if (cancelled) return
          setError(reason)
          retry = setTimeout(attempt, MINT_RETRY_DELAY_MS)
        })
    }
    setError(null)
    attempt()
    return () => {
      cancelled = true
      if (retry) clearTimeout(retry)
    }
  }, [agent, cache, enabled, service])

  const isRequestedPair =
    resolved !== null && resolved.agent === agent && resolved.service === service
  return { key: isRequestedPair ? resolved.key : null, error }
}
