import { describe, expect, it } from "vitest"
import type { HttpClient } from "../transport/http"
import { fetchUserNotifications } from "./user-notification-feed"

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
