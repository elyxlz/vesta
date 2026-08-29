import { useCallback, useEffect, useRef, useState } from "react"
import type { Delta } from "../protocol/deltas"
import type { OrbVisualState } from "../agent-status/agent-status"
import {
  enqueuePillNotification,
  pillVisibleWhileViewing,
  PILL_SHOW_MS,
  type PillNotification,
} from "../notifications-pill/notifications-pill"
import { loggedFromDelta } from "../notifications-pill/user-notification-feed"

/** The one edge the pill needs from the controller. */
export interface PillDeltaSource {
  subscribeDeltas(listener: (delta: Delta) => void): () => void
}

export interface NotificationsPillOptions {
  /** The agent whose page is open, if any: its own messages never show. */
  viewedAgent: string | null
  /** The named agent's orb state right now, or null when unknown to the roster. */
  orbStateFor: (agent: string) => OrbVisualState | null
  /**
   * While true, arriving notifications skip the pill entirely (no queue, no
   * animation). The view sets this while a history surface is open, where
   * arrivals appear in the list instead.
   */
  paused?: boolean
}

/**
 * The notifications pill's whole behavior, shared by every view: subscribes to
 * `user_notification` deltas, groups the queue by kind, snapshots the orb at
 * intake, advances on a timer, and derives the shown item. The view renders
 * `current` and calls `dismiss` when the user taps it.
 */
export function useNotificationsPill(
  source: PillDeltaSource | null,
  options: NotificationsPillOptions,
): { current: PillNotification | null; dismiss: () => void } {
  const [queue, setQueue] = useState<PillNotification[]>([])

  // The delta handler reads the live options through one ref so the
  // subscription survives route and roster changes.
  const optionsRef = useRef(options)
  useEffect(() => {
    optionsRef.current = options
  })

  useEffect(() => {
    if (!source) return
    return source.subscribeDeltas((delta: Delta) => {
      const { viewedAgent, orbStateFor, paused = false } = optionsRef.current
      const item = loggedFromDelta(delta)
      if (!item || paused || !pillVisibleWhileViewing(item, viewedAgent)) return
      const orbState = orbStateFor(item.agent)
      setQueue((current) => enqueuePillNotification(current, { ...item, orbState }))
    })
  }, [source])

  // Keyed on the head's id, not the queue: an enqueue behind the head must not
  // reset the shown item's timer, or a steady stream would starve the rotation.
  // Both the timer and a dismiss remove that one id, so the two racing in one
  // tick drop one item, never two.
  const head = queue[0] ?? null
  const headId = head?.id ?? null
  const remove = useCallback((id: number) => {
    setQueue((queued) => queued.filter((item) => item.id !== id))
  }, [])
  useEffect(() => {
    if (headId === null) return
    const timer = setTimeout(() => {
      remove(headId)
    }, PILL_SHOW_MS)
    return () => {
      clearTimeout(timer)
    }
  }, [headId, remove])

  // Visibility is derived at render: a head the user navigated into (their
  // agent's own message) hides instantly and expires on the advance timer.
  const current = head && pillVisibleWhileViewing(head, options.viewedAgent) ? head : null

  const dismiss = useCallback(() => {
    if (headId !== null) remove(headId)
  }, [headId, remove])

  return { current, dismiss }
}
