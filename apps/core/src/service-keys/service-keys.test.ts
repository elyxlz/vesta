import { afterEach, describe, expect, it, vi } from "vitest"

import {
  createServiceKeyCache,
  isKeyFresh,
  mintServiceKey,
  serviceKeyPathUrl,
  serviceKeyQueryUrl,
  serviceKeySocketUrl,
} from "./service-keys"
import type { HttpClient } from "../transport/http"

const NOW_SECS = 1_800_000_000

function fakeHttp(minted: { key: string; expires_at: number | null }): {
  http: HttpClient
  calls: string[]
  inits: (RequestInit | undefined)[]
} {
  const calls: string[] = []
  const inits: (RequestInit | undefined)[] = []
  let index = 0
  const http: HttpClient = {
    request: () => Promise.reject(new Error("unused")),
    json: <T>(path: string, init?: RequestInit) => {
      calls.push(path)
      inits.push(init)
      index += 1
      return Promise.resolve({ id: `id-${String(index)}`, ...minted } as T)
    },
  }
  return { http, calls, inits }
}

function onlyInit(inits: (RequestInit | undefined)[]): RequestInit {
  const [init] = inits
  if (!init) throw new Error("no request was sent")
  return init
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("mintServiceKey", () => {
  // vestad extracts the body with axum's Json<T>: no content type is a 415 and an empty
  // body a 400, so a mint with nothing to say still sends a literal `{}`.
  it("always POSTs a json body, even with no ttl to ask for", async () => {
    const { http, calls, inits } = fakeHttp({ key: "k", expires_at: null })
    await mintServiceKey(http, "alpha", "dashboard")

    expect(calls).toEqual(["/agents/alpha/services/dashboard/keys"])
    const init = onlyInit(inits)
    expect(init.method).toBe("POST")
    expect(new Headers(init.headers).get("content-type")).toBe("application/json")
    expect(init.body).toBe("{}")
  })

  it("sends a requested ttl as ttl_secs", async () => {
    const { http, inits } = fakeHttp({ key: "k", expires_at: NOW_SECS + 60 })
    await mintServiceKey(http, "alpha", "dashboard", 60)

    expect(onlyInit(inits).body).toBe(JSON.stringify({ ttl_secs: 60 }))
  })

  it("returns the minted key and its expiry", async () => {
    const { http } = fakeHttp({ key: "secret", expires_at: NOW_SECS + 600 })
    const minted = await mintServiceKey(http, "alpha", "dashboard", 600)

    expect(minted.key).toBe("secret")
    expect(minted.expires_at).toBe(NOW_SECS + 600)
    expect(minted.id).toBe("id-1")
  })
})

describe("isKeyFresh", () => {
  it("treats a missing entry as stale", () => {
    expect(isKeyFresh(null, NOW_SECS)).toBe(false)
  })

  it("treats a non-expiring key as always fresh", () => {
    expect(isKeyFresh({ key: "k", expiresAt: null }, 9_000_000_000)).toBe(true)
  })

  it("re-mints before expiry rather than at it", () => {
    expect(isKeyFresh({ key: "k", expiresAt: NOW_SECS + 43_200 }, NOW_SECS)).toBe(true)
    expect(isKeyFresh({ key: "k", expiresAt: NOW_SECS + 60 }, NOW_SECS)).toBe(false)
    expect(isKeyFresh({ key: "k", expiresAt: NOW_SECS - 1 }, NOW_SECS)).toBe(false)
  })
})

describe("createServiceKeyCache", () => {
  it("mints once per agent and service, then reuses the key", async () => {
    const { http, calls } = fakeHttp({ key: "minted", expires_at: null })
    const cache = createServiceKeyCache({ http, gateway: () => "https://gw-a" })
    expect(await cache.get("alpha", "dashboard")).toBe("minted")
    expect(await cache.get("alpha", "dashboard")).toBe("minted")
    expect(calls).toEqual(["/agents/alpha/services/dashboard/keys"])
  })

  it("keeps one entry per agent and service pair", async () => {
    const { http, calls } = fakeHttp({ key: "one", expires_at: null })
    const cache = createServiceKeyCache({ http, gateway: () => "https://gw-a" })
    await cache.get("alpha", "dashboard")
    await cache.get("beta", "dashboard")
    await cache.get("alpha", "voice")
    expect(calls).toHaveLength(3)
  })

  it("re-mints when the cached key is close to expiry", async () => {
    vi.spyOn(Date, "now").mockReturnValue(NOW_SECS * 1000)
    const { http, calls } = fakeHttp({ key: "stale", expires_at: NOW_SECS + 60 })
    const cache = createServiceKeyCache({ http, gateway: () => "https://gw-a" })
    await cache.get("alpha", "dashboard")
    await cache.get("alpha", "dashboard")
    expect(calls).toHaveLength(2)
  })

  // vestad refuses ttl_secs 0, and omitting a ttl silently takes its 30-day default, so the
  // app states the lifetime it wants.
  it("asks for a bounded, non-zero lifetime", async () => {
    const { http, inits } = fakeHttp({ key: "k", expires_at: null })
    const cache = createServiceKeyCache({ http, gateway: () => "https://gw-a" })
    await cache.get("alpha", "dashboard")

    expect(onlyInit(inits).body).toBe(JSON.stringify({ ttl_secs: 12 * 3600 }))
  })

  // Agents share the same default name across gateways, and an app can reconnect elsewhere
  // without reloading, so a key cached under gateway A must not be served at gateway B: it
  // would be refused for hours, with nothing to invalidate it.
  it("re-mints for the same agent and service after reconnecting to another gateway", async () => {
    const { http, calls } = fakeHttp({ key: "k", expires_at: null })
    let gateway = "https://gw-a"
    const cache = createServiceKeyCache({ http, gateway: () => gateway })
    await cache.get("alpha", "dashboard")
    gateway = "https://gw-b"
    await cache.get("alpha", "dashboard")
    expect(calls).toHaveLength(2)
  })

  // Two consumers ask on a cold cache in the same tick: mobile's TTS stream and its STT socket
  // both want the voice key, and React's double effect in dev asks twice. Without one shared
  // in-flight mint each would mint, and the later one would overwrite the other's cached key.
  it("mints once for two callers asking at the same time", async () => {
    const { http, calls } = fakeHttp({ key: "shared", expires_at: null })
    const cache = createServiceKeyCache({ http, gateway: () => "https://gw-a" })

    const [first, second] = await Promise.all([
      cache.get("alpha", "voice"),
      cache.get("alpha", "voice"),
    ])

    expect(calls).toEqual(["/agents/alpha/services/voice/keys"])
    expect(second).toBe(first)
  })

  it("mints again after a failed mint rather than holding on to it", async () => {
    const calls: string[] = []
    const http: HttpClient = {
      request: () => Promise.reject(new Error("unused")),
      json: <T>(path: string) => {
        calls.push(path)
        return calls.length === 1
          ? Promise.reject(new Error("gateway unreachable"))
          : Promise.resolve({ id: "id-2", key: "second", expires_at: null } as T)
      },
    }
    const cache = createServiceKeyCache({ http, gateway: () => "https://gw-a" })

    await expect(cache.get("alpha", "voice")).rejects.toThrow("gateway unreachable")
    expect(await cache.get("alpha", "voice")).toBe("second")
    expect(calls).toHaveLength(2)
  })

  it("percent-encodes the agent and service in the mint path", async () => {
    const { http, calls } = fakeHttp({ key: "k", expires_at: null })
    const cache = createServiceKeyCache({ http, gateway: () => "https://gw-a" })
    await cache.get("a b", "we/ird")
    expect(calls).toEqual(["/agents/a%20b/services/we%2Fird/keys"])
  })
})

describe("url builders", () => {
  it("puts the key in a path prefix relative sub-resources inherit", () => {
    expect(serviceKeyPathUrl("https://host", "alpha", "dashboard", "abc")).toBe(
      "https://host/agents/alpha/dashboard/k/abc/",
    )
  })

  it("puts the key in a query param for media and socket URLs", () => {
    expect(serviceKeyQueryUrl("https://host", "alpha", "voice", "abc", "/tts/stream/one")).toBe(
      "https://host/agents/alpha/voice/tts/stream/one?token=abc",
    )
  })

  it("swaps the scheme to ws(s) for socket URLs", () => {
    expect(serviceKeySocketUrl("https://host", "alpha", "voice", "abc", "/stt/listen")).toBe(
      "wss://host/agents/alpha/voice/stt/listen?token=abc",
    )
    expect(serviceKeySocketUrl("http://host", "alpha", "voice", "abc", "/stt/listen")).toBe(
      "ws://host/agents/alpha/voice/stt/listen?token=abc",
    )
  })

  it("percent-encodes every caller-supplied segment", () => {
    expect(serviceKeyPathUrl("https://host", "a b", "dash board", "a/b")).toBe(
      "https://host/agents/a%20b/dash%20board/k/a%2Fb/",
    )
    expect(serviceKeyQueryUrl("https://host", "a b", "dash board", "a/b", "/tts")).toBe(
      "https://host/agents/a%20b/dash%20board/tts?token=a%2Fb",
    )
  })
})
