import { describe, expect, it, vi } from "vitest"

import { ApiError, createHttpClient } from "./http"
import type { FetchLike, HttpDeps } from "./http"

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function deps(fetch: FetchLike, over: Partial<HttpDeps> = {}): HttpDeps {
  return {
    baseUrl: () => "https://vestad.test",
    fetch,
    token: () => "tok",
    refresh: () => Promise.resolve(true),
    ...over,
  }
}

describe("createHttpClient", () => {
  it("sends the bearer token and returns parsed JSON", async () => {
    const fetch = vi.fn<FetchLike>().mockResolvedValue(jsonResponse(200, { ok: true }))
    const client = createHttpClient(deps(fetch))
    const body = await client.json<{ ok: boolean }>("/agents")
    expect(body).toEqual({ ok: true })
    const call = fetch.mock.calls.at(0)
    expect(call?.[0]).toBe("https://vestad.test/agents")
    expect(new Headers(call?.[1]?.headers).get("Authorization")).toBe("Bearer tok")
  })

  it("omits the header when no token is available", async () => {
    const fetch = vi.fn<FetchLike>().mockResolvedValue(jsonResponse(200, {}))
    const client = createHttpClient(deps(fetch, { token: () => null }))
    await client.request("/agents")
    const call = fetch.mock.calls.at(0)
    expect(new Headers(call?.[1]?.headers).has("Authorization")).toBe(false)
  })

  it("refreshes once on 401 and retries", async () => {
    const fetch = vi
      .fn<FetchLike>()
      .mockResolvedValueOnce(new Response("nope", { status: 401 }))
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }))
    const refresh = vi.fn<() => Promise<boolean>>().mockResolvedValue(true)
    const client = createHttpClient(deps(fetch, { refresh }))
    await client.request("/agents")
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it("throws ApiError when the refresh fails on a 401", async () => {
    const fetch = vi.fn<FetchLike>().mockResolvedValue(new Response("nope", { status: 401 }))
    const client = createHttpClient(deps(fetch, { refresh: () => Promise.resolve(false) }))
    await expect(client.request("/agents")).rejects.toBeInstanceOf(ApiError)
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it("does not refresh a second time when the retried request is still 401", async () => {
    const fetch = vi
      .fn<FetchLike>()
      .mockResolvedValueOnce(new Response("nope", { status: 401 }))
      .mockResolvedValueOnce(new Response("still nope", { status: 401 }))
    const refresh = vi.fn<() => Promise<boolean>>().mockResolvedValue(true)
    const client = createHttpClient(deps(fetch, { refresh }))
    await expect(client.request("/agents")).rejects.toMatchObject({ status: 401 })
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it("throws ApiError with the server error message", async () => {
    const fetch = vi.fn<FetchLike>().mockResolvedValue(jsonResponse(409, { error: "name taken" }))
    const client = createHttpClient(deps(fetch))
    await expect(client.request("/agents")).rejects.toMatchObject({
      status: 409,
      message: "name taken",
    })
  })

  it("refreshes before sending when the token is expiring", async () => {
    const fetch = vi.fn<FetchLike>().mockResolvedValue(jsonResponse(200, {}))
    const refresh = vi.fn<() => Promise<boolean>>().mockResolvedValue(true)
    const client = createHttpClient(deps(fetch, { refresh, isExpiring: () => true }))
    await client.request("/agents")
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it("does not refresh before sending when the token is fresh", async () => {
    const fetch = vi.fn<FetchLike>().mockResolvedValue(jsonResponse(200, {}))
    const refresh = vi.fn<() => Promise<boolean>>().mockResolvedValue(true)
    const client = createHttpClient(deps(fetch, { refresh, isExpiring: () => false }))
    await client.request("/agents")
    expect(refresh).not.toHaveBeenCalled()
  })

  it("shapes the error message through an injected formatter", async () => {
    const fetch = vi
      .fn<FetchLike>()
      .mockResolvedValue(new Response("<html>oops</html>", { status: 502 }))
    const client = createHttpClient(
      deps(fetch, { formatError: (response) => `gateway ${String(response.status)}` }),
    )
    await expect(client.request("/agents")).rejects.toMatchObject({
      status: 502,
      message: "gateway 502",
    })
  })
})
