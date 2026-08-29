import { useCallback, useEffect, useReducer } from "react"
import type { Controller } from "../controller/controller"
import type { Delta } from "../protocol/deltas"
import {
  EMPTY_FEED,
  feedNeedsMarkSeen,
  reduceFeed,
  type NotificationFeed,
} from "../notifications-pill/notification-feed"
import {
  fetchUserNotifications,
  loggedFromDelta,
  markUserNotificationsSeen,
} from "../notifications-pill/user-notification-feed"

export interface NotificationFeedOptions {
  pageSize: number
  /**
   * A newest page loaded into an empty feed shows its skeletons for at least
   * this long, so a near-instant answer reads as a loading state, not a flash.
   */
  minLoadingMs: number
}

export interface NotificationFeedHandle {
  feed: NotificationFeed
  /** A history surface opened: hold the watermark and (re)load the newest page. */
  open: (seenAt: number) => void
  /** The last history surface closed: mark the feed seen if anything unseen was on offer. */
  close: (lastAt: number | null) => void
  loadOlder: () => void
}

/**
 * The feed's whole behavior, shared by every view: the live edge always flows
 * in (open or closed, so a reopened surface is current before its refresh
 * lands), each open refetches the newest page and merges it by id, and the
 * gateway's watermark is what "seen" means.
 */
export function useNotificationFeed(
  controller: Controller | null,
  { pageSize, minLoadingMs }: NotificationFeedOptions,
): NotificationFeedHandle {
  const [feed, dispatch] = useReducer(reduceFeed, EMPTY_FEED)

  useEffect(() => {
    if (!controller) return
    return controller.subscribeDeltas((delta: Delta) => {
      const entry = loggedFromDelta(delta)
      if (entry) dispatch({ type: "arrived", entry })
    })
  }, [controller])

  const empty = feed.entries.length === 0
  const loadPage = useCallback(
    (before?: number) => {
      if (!controller) return
      dispatch({ type: "page_loading", before })
      const hold = before === undefined && empty ? minLoadingMs : 0
      const held = new Promise((resolve) => setTimeout(resolve, hold))
      const page = fetchUserNotifications(controller.http, { before, limit: pageSize })
      // allSettled, never all: a failing fetch still waits out the skeletons' hold.
      void Promise.allSettled([page, held]).then(([result]) => {
        if (result.status === "fulfilled") {
          dispatch({ type: "page_loaded", page: result.value, before, pageSize })
        } else {
          dispatch({ type: "page_failed", before })
        }
      })
    },
    [controller, empty, minLoadingMs, pageSize],
  )

  const open = useCallback(
    (seenAt: number) => {
      dispatch({ type: "open", seenAt })
      loadPage()
    },
    [loadPage],
  )

  const close = useCallback(
    (lastAt: number | null) => {
      dispatch({ type: "close" })
      if (controller && feedNeedsMarkSeen(feed, lastAt)) {
        markUserNotificationsSeen(controller.http).catch(() => undefined)
      }
    },
    [controller, feed],
  )

  const oldestEntry = feed.entries[feed.entries.length - 1]
  const loadOlder = useCallback(() => {
    if (oldestEntry !== undefined) loadPage(oldestEntry.id)
  }, [loadPage, oldestEntry])

  // With a surface open on a real watermark, page back until the loaded history
  // reaches past it, so the "new" section can offer the whole unseen set. A 0
  // watermark (never caught up) does not page: everything logged is unseen.
  useEffect(() => {
    if (!feed.open || feed.seenAt === null || feed.seenAt === 0) return
    if (feed.newest !== "ready" || feed.older !== "more") return
    if (oldestEntry !== undefined && oldestEntry.at > feed.seenAt) loadOlder()
  }, [feed.open, feed.seenAt, feed.newest, feed.older, oldestEntry, loadOlder])

  return { feed, open, close, loadOlder }
}
