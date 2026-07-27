import type { HttpClient } from "../transport/http"

// A service key opens exactly one service on one agent. It is the only credential the
// dashboard frame and the voice media URLs ever carry, so the api key and access tokens
// stay out of every service URL. vestad keeps only a hash, so a key cannot be re-read: a
// cache miss simply mints a fresh one.
export interface ServiceKey {
  id: string
  key: string
  expires_at: number | null
}

export interface CachedServiceKey {
  key: string
  expiresAt: number | null
}

export interface ServiceKeyCache {
  get: (agent: string, service: string) => Promise<string>
}

// The margin `get` demands of a cached key: anything handed out has more than an hour of life
// left. Freshness is only ever evaluated on the way out, so a consumer holding a key past its
// expiry keeps holding it until it asks again.
const REMINT_MARGIN_SECS = 3600
// Lifetime the app asks for: long enough that an open dashboard rarely remounts, short
// enough that a leaked URL stops working the same day.
const APP_KEY_TTL_SECS = 12 * 3600

// The one owner of the mint request, mirroring intents/gateway-update.ts: it takes core's
// HttpClient, so web and mobile share it along with their own auth and refresh wiring.
// The body and its content type are not optional: vestad extracts Json<T>, so a bodyless
// POST is a 415 and an empty one a 400. Only a literal `{}` reaches the serde defaults.
export async function mintServiceKey(
  http: HttpClient,
  agent: string,
  service: string,
  ttlSecs?: number,
): Promise<ServiceKey> {
  return http.json<ServiceKey>(
    `/agents/${encodeURIComponent(agent)}/services/${encodeURIComponent(service)}/keys`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ttlSecs === undefined ? {} : { ttl_secs: ttlSecs }),
    },
  )
}

export function isKeyFresh(entry: CachedServiceKey | null, nowSecs: number): boolean {
  if (!entry) return false
  if (entry.expiresAt === null) return true
  return entry.expiresAt - nowSecs > REMINT_MARGIN_SECS
}

// A factory rather than module state, so a test builds its own and two connections never
// share keys.
export function createServiceKeyCache(deps: {
  http: HttpClient
  // Which gateway minted the key. A key is only valid at the gateway that issued it, so the
  // gateway is part of the cache identity: reconnecting elsewhere must miss rather than serve a
  // key the new gateway will refuse.
  gateway: () => string | null
}): ServiceKeyCache {
  const cached = new Map<string, CachedServiceKey>()
  // Mints in flight, so two callers asking at once (a TTS stream and an STT socket, or React's
  // double effect in dev) share one mint instead of racing to overwrite each other's key. The
  // entry goes as soon as the mint settles, so a failure is retried rather than kept.
  const minting = new Map<string, Promise<string>>()
  return {
    get: async (agent, service) => {
      const cacheKey = `${deps.gateway() ?? ""}/${agent}/${service}`
      const nowSecs = Math.floor(Date.now() / 1000)
      const existing = cached.get(cacheKey) ?? null
      if (existing && isKeyFresh(existing, nowSecs)) return existing.key
      const inFlight = minting.get(cacheKey)
      if (inFlight) return inFlight
      const pending = mintServiceKey(deps.http, agent, service, APP_KEY_TTL_SECS)
        .then((minted) => {
          cached.set(cacheKey, { key: minted.key, expiresAt: minted.expires_at })
          return minted.key
        })
        .finally(() => {
          minting.delete(cacheKey)
        })
      minting.set(cacheKey, pending)
      return pending
    },
  }
}

// The path form. A prefix is the only carrier a relative sub-resource inherits, which is
// how an iframe's assets authenticate with no header and no query string.
export function serviceKeyPathUrl(
  baseUrl: string,
  agent: string,
  service: string,
  key: string,
): string {
  const agentSegment = encodeURIComponent(agent)
  const serviceSegment = encodeURIComponent(service)
  return `${baseUrl}/agents/${agentSegment}/${serviceSegment}/k/${encodeURIComponent(key)}/`
}

// The query form, for a media element or a WebSocket, neither of which can send a header.
export function serviceKeyQueryUrl(
  baseUrl: string,
  agent: string,
  service: string,
  key: string,
  // Appended verbatim after the service segment: it must start with a slash and carry no query
  // string of its own, or the result is a run-on path or a url with two `?`.
  subpath: string,
): string {
  const params = new URLSearchParams({ token: key })
  const agentSegment = encodeURIComponent(agent)
  const serviceSegment = encodeURIComponent(service)
  return `${baseUrl}/agents/${agentSegment}/${serviceSegment}${subpath}?${params.toString()}`
}
