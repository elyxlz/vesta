import { feedHasUnseen, splitBySeen, type LoggedUserNotification } from "./user-notification-feed"

// The user-notification feed as one state machine, shared by every view: the
// durable log's pages and the live `user_notification` edge join into a single
// id-keyed list (a live arrival and the page that later contains it are the
// same row), and the catch-up session holds the seen watermark it opened with.

/** The newest page's lifecycle; the skeletons show while it is `idle` or `loading` with no rows. */
export type NewestPageStatus = "idle" | "loading" | "ready" | "failed"
/** Whether the archive extends past the oldest loaded row. */
export type OlderPagesStatus = "more" | "loading" | "exhausted" | "failed"

export interface NotificationFeed {
  /** Newest first, unique by id. */
  entries: LoggedUserNotification[]
  /** Rows that arrived over the socket during this session (the ones a view animates in). */
  liveIds: number[]
  newest: NewestPageStatus
  older: OlderPagesStatus
  /** A history surface is on screen. */
  open: boolean
  /**
   * The seen watermark as it stood when the latest session opened, kept after
   * close so a surface animating out renders exactly what it showed; null
   * before the first session ever. 0 means the user never caught up.
   */
  seenAt: number | null
}

export const EMPTY_FEED: NotificationFeed = {
  entries: [],
  liveIds: [],
  newest: "idle",
  older: "more",
  open: false,
  seenAt: null,
}

export type FeedAction =
  | { type: "open"; seenAt: number }
  | { type: "close" }
  | { type: "arrived"; entry: LoggedUserNotification }
  | { type: "page_loading"; before?: number }
  | { type: "page_loaded"; page: LoggedUserNotification[]; before?: number; pageSize: number }
  | { type: "page_failed"; before?: number }

export function reduceFeed(feed: NotificationFeed, action: FeedAction): NotificationFeed {
  switch (action.type) {
    case "open":
      if (feed.open) return feed
      return { ...feed, open: true, seenAt: action.seenAt, liveIds: [] }
    case "close":
      return { ...feed, open: false }
    case "arrived":
      if (feed.entries.some((item) => item.id === action.entry.id)) return feed
      return {
        ...feed,
        entries: merge(feed.entries, [action.entry]),
        liveIds: [...feed.liveIds, action.entry.id],
      }
    case "page_loading":
      return action.before === undefined
        ? { ...feed, newest: "loading" }
        : { ...feed, older: "loading" }
    case "page_loaded": {
      const short = action.page.length < action.pageSize
      const entries = merge(feed.entries, action.page)
      if (action.before === undefined) {
        return { ...feed, entries, newest: "ready", older: short ? "exhausted" : feed.older }
      }
      return { ...feed, entries, older: short ? "exhausted" : "more" }
    }
    case "page_failed":
      return action.before === undefined
        ? { ...feed, newest: "failed" }
        : { ...feed, older: "failed" }
  }
}

function merge(
  existing: LoggedUserNotification[],
  incoming: LoggedUserNotification[],
): LoggedUserNotification[] {
  const byId = new Map(existing.map((item) => [item.id, item]))
  for (const item of incoming) byId.set(item.id, item)
  return [...byId.values()].sort((a, b) => b.id - a.id)
}

/**
 * Whether closing the session should tell the gateway the user caught up:
 * something is past the held watermark, by the gateway's newest stamp or by a
 * loaded row (a live arrival can land before the stamp's own delta).
 */
export function feedNeedsMarkSeen(feed: NotificationFeed, lastAt: number | null): boolean {
  if (feed.seenAt === null) return false
  const seenAt = feed.seenAt
  return feedHasUnseen(lastAt, seenAt) || feed.entries.some((item) => item.at > seenAt)
}

/** The unseen/seen split, or null when the feed renders as one plain list. */
export type FeedSections = {
  unseen: LoggedUserNotification[]
  seen: LoggedUserNotification[]
} | null

/**
 * The unseen/seen split against the held watermark, or null when the feed
 * renders as one plain list: before the first session, and for a user who
 * never caught up (everything would be "new", so a split only adds noise).
 */
export function feedSections(feed: NotificationFeed): FeedSections {
  if (feed.seenAt === null || feed.seenAt === 0) return null
  return splitBySeen(feed.entries, feed.seenAt)
}

export type FeedView = "loading" | "failed" | "empty" | "rows"

/** What a history surface shows: rows whenever there are any, else the newest page's state. */
export function feedView(feed: NotificationFeed): FeedView {
  if (feed.entries.length > 0) return "rows"
  if (feed.newest === "failed") return "failed"
  if (feed.newest === "ready") return "empty"
  return "loading"
}
