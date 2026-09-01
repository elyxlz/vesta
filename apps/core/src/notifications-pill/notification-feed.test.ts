import { describe, expect, it } from "vitest"
import {
  EMPTY_FEED,
  feedNeedsMarkSeen,
  feedSections,
  feedUnseen,
  feedView,
  reduceFeed,
  type FeedAction,
  type NotificationFeed,
} from "./notification-feed"
import type { LoggedUserNotification } from "./user-notification-feed"

const PAGE_SIZE = 3

function entry(id: number, at = id * 100): LoggedUserNotification {
  return { id, at, agent: "aria", kind: "message", title: "aria", body: `n${String(id)}` }
}

function run(actions: FeedAction[], from: NotificationFeed = EMPTY_FEED): NotificationFeed {
  return actions.reduce(reduceFeed, from)
}

function ids(feed: NotificationFeed): number[] {
  return feed.entries.map((item) => item.id)
}

describe("reduceFeed: the live edge", () => {
  it("lands a live arrival at the top, once, and remembers it as live", () => {
    const feed = run([
      { type: "arrived", readInPlace: false, entry: entry(5) },
      { type: "arrived", readInPlace: false, entry: entry(5) },
      { type: "arrived", readInPlace: false, entry: entry(6) },
    ])
    expect(ids(feed)).toEqual([6, 5])
    expect(feed.liveIds).toEqual([5, 6])
  })
})

describe("reduceFeed: pages", () => {
  it("merges the newest page into what the live edge already delivered, by id", () => {
    const feed = run([
      { type: "arrived", readInPlace: false, entry: entry(6) },
      { type: "page_loading" },
      { type: "page_loaded", page: [entry(6), entry(5), entry(4)], pageSize: PAGE_SIZE },
    ])
    expect(ids(feed)).toEqual([6, 5, 4])
    expect(feed.newest).toBe("ready")
    expect(feed.older).toBe("more")
  })

  it("appends an older page and a short page exhausts the archive", () => {
    const feed = run([
      { type: "page_loaded", page: [entry(6), entry(5), entry(4)], pageSize: PAGE_SIZE },
      { type: "page_loading", before: 4 },
      { type: "page_loaded", page: [entry(3)], before: 4, pageSize: PAGE_SIZE },
    ])
    expect(ids(feed)).toEqual([6, 5, 4, 3])
    expect(feed.older).toBe("exhausted")
  })

  it("keeps the archive exhausted when a later newest page comes back full", () => {
    const feed = run([
      { type: "page_loaded", page: [entry(2), entry(1)], pageSize: PAGE_SIZE },
      { type: "arrived", readInPlace: false, entry: entry(3) },
      { type: "page_loaded", page: [entry(3), entry(2), entry(1)], pageSize: PAGE_SIZE },
    ])
    expect(feed.older).toBe("exhausted")
  })

  it("marks a failed newest load without touching the rows already loaded", () => {
    const feed = run([
      { type: "page_loaded", page: [entry(2), entry(1)], pageSize: PAGE_SIZE },
      { type: "page_loading" },
      { type: "page_failed" },
    ])
    expect(ids(feed)).toEqual([2, 1])
    expect(feed.newest).toBe("failed")
  })

  it("marks a failed older load on its own slot, and a retry clears it", () => {
    const failed = run([
      { type: "page_loaded", page: [entry(6), entry(5), entry(4)], pageSize: PAGE_SIZE },
      { type: "page_loading", before: 4 },
      { type: "page_failed", before: 4 },
    ])
    expect(failed.newest).toBe("ready")
    expect(failed.older).toBe("failed")
    expect(run([{ type: "page_loading", before: 4 }], failed).older).toBe("loading")
  })
})

describe("reduceFeed: the catch-up session", () => {
  it("snapshots the watermark on open and holds it through close, so the split never shifts", () => {
    const opened = run([
      { type: "page_loaded", page: [entry(3), entry(2), entry(1)], pageSize: PAGE_SIZE },
      { type: "open", seenAt: 150 },
      { type: "open", seenAt: 999 },
    ])
    expect(opened.open).toBe(true)
    expect(opened.seenAt).toBe(150)
    const closed = reduceFeed(opened, { type: "close" })
    expect(closed.open).toBe(false)
    expect(feedSections(closed)).toEqual(feedSections(opened))
    expect(feedSections(closed)?.unseen.map((item) => item.id)).toEqual([3, 2])
  })

  it("re-snapshots the watermark on the next open and forgets which rows were live", () => {
    const feed = run([
      { type: "open", seenAt: 150 },
      { type: "arrived", readInPlace: false, entry: entry(3) },
      { type: "close" },
      { type: "open", seenAt: 300 },
    ])
    expect(feed.seenAt).toBe(300)
    expect(feed.liveIds).toEqual([])
  })
})

describe("feedNeedsMarkSeen", () => {
  it("asks for a catch-up when the gateway's newest stamp or a loaded row is past the held watermark", () => {
    const held = run([{ type: "open", seenAt: 150 }, { type: "close" }])
    expect(feedNeedsMarkSeen(held, 200)).toBe(true)
    expect(feedNeedsMarkSeen(held, 150)).toBe(false)
    expect(
      feedNeedsMarkSeen(run([{ type: "arrived", readInPlace: false, entry: entry(2) }], held), 150),
    ).toBe(true)
  })

  it("never asks before a session ever opened", () => {
    expect(
      feedNeedsMarkSeen(run([{ type: "arrived", readInPlace: false, entry: entry(2) }]), 500),
    ).toBe(false)
  })
})

describe("feedUnseen", () => {
  // A loaded feed is the precondition for discounting anything, so each case
  // starts from a ready newest page.
  function loaded(actions: FeedAction[]): NotificationFeed {
    return run([{ type: "page_loaded", page: [], pageSize: PAGE_SIZE }, ...actions])
  }

  it("does not raise the dot for a notification the user read in the chat", () => {
    const feed = loaded([{ type: "arrived", readInPlace: true, entry: entry(3, 300) }])
    expect(feedUnseen(feed, 300, 200)).toBe(false)
  })

  it("still raises the dot for anything alongside it the user has not read", () => {
    const feed = loaded([
      { type: "arrived", readInPlace: false, entry: entry(3, 300) },
      { type: "arrived", readInPlace: true, entry: entry(4, 400) },
    ])
    expect(feedUnseen(feed, 400, 200)).toBe(true)
  })

  it("keeps the dot for what it cannot account for: an unloaded feed or a stamp above every row", () => {
    const unloaded = run([{ type: "arrived", readInPlace: true, entry: entry(3, 300) }])
    expect(feedUnseen(unloaded, 300, 200)).toBe(true)
    const feed = loaded([{ type: "arrived", readInPlace: true, entry: entry(3, 300) }])
    expect(feedUnseen(feed, 400, 200)).toBe(true)
  })

  it("stays down while the gateway's scalars report nothing new", () => {
    const feed = loaded([{ type: "arrived", readInPlace: false, entry: entry(3, 300) }])
    expect(feedUnseen(feed, 300, 300)).toBe(false)
    expect(feedUnseen(feed, null, 0)).toBe(false)
  })

  it("holds the dot down after close marks seen, until the synced watermark catches up", () => {
    const seen = loaded([
      { type: "arrived", readInPlace: false, entry: entry(3, 300) },
      { type: "marked_seen", seenAt: 300 },
    ])
    // Synced watermark still lags at 200, but the optimistic floor keeps the dot down.
    expect(feedUnseen(seen, 300, 200)).toBe(false)
    // A newer arrival out-stamps the floor and raises the dot again.
    const newer = reduceFeed(seen, {
      type: "arrived",
      readInPlace: false,
      entry: entry(4, 400),
    })
    expect(feedUnseen(newer, 400, 200)).toBe(true)
  })
})

describe("feedSections", () => {
  it("splits on the held watermark, and stays unsectioned before the first open or when never caught up", () => {
    const loaded = run([{ type: "page_loaded", page: [entry(2), entry(1)], pageSize: PAGE_SIZE }])
    expect(feedSections(loaded)).toBeNull()
    expect(feedSections(reduceFeed(loaded, { type: "open", seenAt: 0 }))).toBeNull()
    const sections = feedSections(reduceFeed(loaded, { type: "open", seenAt: 100 }))
    expect(sections?.unseen.map((item) => item.id)).toEqual([2])
    expect(sections?.seen.map((item) => item.id)).toEqual([1])
  })
})

describe("feedView", () => {
  it("reads loading until the first page answers, then failed, empty, or rows", () => {
    expect(feedView(EMPTY_FEED)).toBe("loading")
    expect(feedView(run([{ type: "page_loading" }]))).toBe("loading")
    expect(feedView(run([{ type: "page_failed" }]))).toBe("failed")
    expect(feedView(run([{ type: "page_loaded", page: [], pageSize: PAGE_SIZE }]))).toBe("empty")
    expect(feedView(run([{ type: "arrived", readInPlace: false, entry: entry(1) }]))).toBe("rows")
    expect(
      feedView(
        run([{ type: "arrived", readInPlace: false, entry: entry(1) }, { type: "page_failed" }]),
      ),
    ).toBe("rows")
  })
})
