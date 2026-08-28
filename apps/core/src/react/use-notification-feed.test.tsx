// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest"
import { act, cleanup, renderHook, waitFor } from "@testing-library/react"

import { useNotificationFeed } from "./use-notification-feed"
import { createReplica } from "../replica/store"
import type { Controller } from "../controller/controller"
import type { Delta } from "../protocol/deltas"
import type { LoggedUserNotification } from "../notifications-pill/user-notification-feed"

const PAGE_SIZE = 2

function entry(id: number): LoggedUserNotification {
  return { id, at: id * 100, agent: "aria", kind: "message", title: "aria", body: `n${String(id)}` }
}

function harness(pages: Record<string, LoggedUserNotification[] | Error>) {
  const listeners = new Set<(delta: Delta) => void>()
  const requests: string[] = []
  const controller: Controller = {
    replica: createReplica(),
    http: {
      request: (path) => {
        requests.push(path)
        return Promise.resolve(new Response(null, { status: 200 }))
      },
      json: <T,>(path: string) => {
        requests.push(path)
        const page = pages[path]
        if (page === undefined) return Promise.reject(new Error(`unexpected ${path}`))
        if (page instanceof Error) return Promise.reject(page)
        return Promise.resolve({ notifications: page } as T)
      },
    },
    reauth: () => undefined,
    subscribeDeltas: (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    getSyncState: () => "open",
    subscribeSyncState: () => () => undefined,
    reportPresence: () => undefined,
    reportViewing: () => undefined,
    reportDeviceContext: () => undefined,
    getAnyFocused: () => false,
    subscribeAnyFocused: () => () => undefined,
    close: () => undefined,
  }
  const emit = (item: LoggedUserNotification): void => {
    for (const listener of listeners) listener({ type: "user_notification", ...item })
  }
  const hook = renderHook(() =>
    useNotificationFeed(controller, { pageSize: PAGE_SIZE, minLoadingMs: 0 }),
  )
  return { ...hook, emit, requests }
}

afterEach(cleanup)

describe("useNotificationFeed", () => {
  it("joins a live arrival to the page that later contains it", async () => {
    const h = harness({ "/notifications?limit=2": [entry(3), entry(2)] })
    act(() => {
      h.result.current.open(100)
    })
    act(() => {
      h.emit(entry(3))
    })
    expect(h.result.current.feed.entries.map((item) => item.id)).toEqual([3])
    await waitFor(() => {
      expect(h.result.current.feed.newest).toBe("ready")
    })
    expect(h.result.current.feed.entries.map((item) => item.id)).toEqual([3, 2])
    expect(h.result.current.feed.liveIds).toEqual([3])
  })

  it("marks the feed seen on close only when something was past the held watermark", async () => {
    const h = harness({ "/notifications?limit=2": [entry(3), entry(2)] })
    act(() => {
      h.result.current.open(300)
    })
    await waitFor(() => {
      expect(h.result.current.feed.newest).toBe("ready")
    })
    act(() => {
      h.result.current.close(300)
    })
    expect(h.requests).not.toContain("/notifications/seen")
    act(() => {
      h.result.current.open(300)
    })
    act(() => {
      h.emit(entry(4))
    })
    act(() => {
      h.result.current.close(300)
    })
    expect(h.requests.filter((path) => path === "/notifications/seen")).toHaveLength(1)
  })

  it("pages older rows from the oldest loaded id and reports a failed page on its own slot", async () => {
    const h = harness({
      "/notifications?limit=2": [entry(3), entry(2)],
      "/notifications?before=2&limit=2": new Error("boom"),
    })
    act(() => {
      h.result.current.open(0)
    })
    await waitFor(() => {
      expect(h.result.current.feed.newest).toBe("ready")
    })
    act(() => {
      h.result.current.loadOlder()
    })
    await waitFor(() => {
      expect(h.result.current.feed.older).toBe("failed")
    })
    expect(h.result.current.feed.newest).toBe("ready")
    expect(h.result.current.feed.entries).toHaveLength(2)
  })

  it("pages back until the loaded history reaches past the held watermark", async () => {
    const h = harness({
      "/notifications?limit=2": [entry(5), entry(4)],
      "/notifications?before=4&limit=2": [entry(3), entry(2)],
    })
    act(() => {
      h.result.current.open(250)
    })
    await waitFor(() => {
      expect(h.result.current.feed.entries.map((item) => item.id)).toEqual([5, 4, 3, 2])
    })
    // entry 2 (at 200) sits under the watermark, so paging stops there without a
    // third fetch, and the archive is not marked exhausted.
    expect(h.requests).not.toContain("/notifications?before=2&limit=2")
    expect(h.result.current.feed.older).toBe("more")
  })

  it("does not page back for a user who never caught up", async () => {
    const h = harness({ "/notifications?limit=2": [entry(3), entry(2)] })
    act(() => {
      h.result.current.open(0)
    })
    await waitFor(() => {
      expect(h.result.current.feed.newest).toBe("ready")
    })
    expect(h.requests).not.toContain("/notifications?before=2&limit=2")
  })
})
