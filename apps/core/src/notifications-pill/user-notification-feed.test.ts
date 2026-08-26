import { describe, expect, it } from "vitest"
import type { HttpClient } from "../transport/http"
import {
  feedHasUnseen,
  fetchUserNotifications,
  markUserNotificationsSeen,
  splitBySeen,
} from "./user-notification-feed"

function httpReturning(payload: unknown, seen: string[]): HttpClient {
  return {
    request: () => Promise.reject(new Error("unused")),
    json: <T>(path: string) => {
      seen.push(path)
      return Promise.resolve(payload as T)
    },
  }
}

const entry = {
  id: 3,
  at: 1700000000,
  agent: "aria",
  kind: "message",
  title: "aria",
  body: "hi",
}

describe("fetchUserNotifications", () => {
  it("pages with the id cursor and parses entries at the boundary", async () => {
    const seen: string[] = []
    const http = httpReturning(
      { notifications: [entry, { id: "bad" }, { ...entry, id: 2, extra: "ignored" }] },
      seen,
    )
    const result = await fetchUserNotifications(http, { before: 10, limit: 2 })
    expect(seen).toEqual(["/notifications?before=10&limit=2"])
    expect(result.map((notification) => notification.id)).toEqual([3, 2])
  })

  it("asks for the newest page with no options and tolerates a missing list", async () => {
    const seen: string[] = []
    const result = await fetchUserNotifications(httpReturning({}, seen))
    expect(seen).toEqual(["/notifications"])
    expect(result).toEqual([])
  })
})

describe("splitBySeen", () => {
  it("splits on the watermark, keeping order within each side", () => {
    const page = [
      { ...entry, id: 3, at: 300 },
      { ...entry, id: 2, at: 200 },
      { ...entry, id: 1, at: 100 },
    ]
    const { unseen, seen } = splitBySeen(page, 200)
    expect(unseen.map((notification) => notification.id)).toEqual([3])
    expect(seen.map((notification) => notification.id)).toEqual([2, 1])
  })

  it("treats a zero watermark as nothing ever seen", () => {
    const { unseen, seen } = splitBySeen([entry], 0)
    expect(unseen).toHaveLength(1)
    expect(seen).toHaveLength(0)
  })
})

describe("feedHasUnseen", () => {
  it("derives the dot from the gateway branch's two scalars", () => {
    expect(feedHasUnseen(200, 100)).toBe(true)
    expect(feedHasUnseen(200, 200)).toBe(false)
    // An empty log or an older gateway (both fields absent) never raises the dot.
    expect(feedHasUnseen(null, 0)).toBe(false)
    expect(feedHasUnseen(undefined, undefined)).toBe(false)
  })
})

describe("markUserNotificationsSeen", () => {
  it("POSTs the catch-up to the gateway", async () => {
    const calls: { path: string; method: string | undefined }[] = []
    const http: HttpClient = {
      request: (path, init) => {
        calls.push({ path, method: init?.method })
        return Promise.resolve(new Response(null, { status: 200 }))
      },
      json: () => Promise.reject(new Error("unused")),
    }
    await markUserNotificationsSeen(http)
    expect(calls).toEqual([{ path: "/notifications/seen", method: "POST" }])
  })
})
