import { useCallback, useEffect, useReducer, useRef } from "react"
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
import { notificationReadInPlace } from "../notifications-pill/notifications-pill"

export interface NotificationFeedOptions {
  pageSize: number
  /** The agent whose page is open, if any. */
  viewedAgent: string | null
  /** Whether this client's window has the user's attention right now. */
  focused: boolean
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
 * lands), the newest page is prefetched the moment the controller exists (so
 * the first open renders from memory, never a skeleton), each open refetches
 * that page and merges it by id, and the gateway's watermark is what "seen"
 * means.
 */
export function useNotificationFeed(
  controller: Controller | null,
  options: NotificationFeedOptions,
): NotificationFeedHandle {
  const { pageSize } = options
  const [feed, dispatch] = useReducer(reduceFeed, EMPTY_FEED)

  // Read through a ref, as the pill does: the subscription outlives every route
  // and focus change, and each arrival is judged against the moment it landed.
  const optionsRef = useRef(options)
  useEffect(() => {
    optionsRef.current = options
  })

  useEffect(() => {
    if (!controller) return
    return controller.subscribeDeltas((delta: Delta) => {
      const entry = loggedFromDelta(delta)
      if (!entry) return
      const { viewedAgent, focused } = optionsRef.current
      dispatch({
        type: "arrived",
        entry,
        readInPlace: notificationReadInPlace(entry, viewedAgent, focused),
      })
    })
  }, [controller])

  const loadPage = useCallback(
    (before?: number) => {
      if (!controller) return
      dispatch({ type: "page_loading", before })
      void fetchUserNotifications(controller.http, { before, limit: pageSize }).then(
        (page) => {
          dispatch({ type: "page_loaded", page, before, pageSize })
        },
        () => {
          dispatch({ type: "page_failed", before })
        },
      )
    },
    [controller, pageSize],
  )

  // The prefetch: one newest-page load as soon as the controller is there,
  // before any surface opens. A failed prefetch stays "failed" (no retry loop);
  // the next open refetches as every open does.
  const newestStatus = feed.newest
  useEffect(() => {
    if (newestStatus === "idle") loadPage()
  }, [newestStatus, loadPage])

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
