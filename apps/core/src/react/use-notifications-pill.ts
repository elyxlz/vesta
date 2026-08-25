import { useEffect, useRef, useState } from "react"
import type { Delta } from "../protocol/deltas"
import type { OrbVisualState } from "../agent-status/agent-status"
import {
  enqueuePillNotification,
  pillContentFromDelta,
  pillVisibleWhileViewing,
  PILL_SHOW_MS,
  type PillContent,
  type PillNotification,
} from "../notifications-pill/notifications-pill"

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
   * animation); they still reach `onNotification`. The view sets this while a
   * history surface is open, where arrivals should just appear in the list.
   */
  paused?: boolean
  /** Fired for every notification taken in, before the pill queues it. */
  onNotification?: (item: PillContent) => void
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
  const { viewedAgent, orbStateFor, paused = false, onNotification } = options
  const [queue, setQueue] = useState<PillNotification[]>([])
  const nextIdRef = useRef(0)

  // The delta handler reads the viewed agent and orb resolver from refs so
  // the subscription survives route and roster changes.
  const viewedRef = useRef(viewedAgent)
  useEffect(() => {
    viewedRef.current = viewedAgent
  }, [viewedAgent])
  const orbStateForRef = useRef(orbStateFor)
  useEffect(() => {
    orbStateForRef.current = orbStateFor
  }, [orbStateFor])
  const onNotificationRef = useRef(onNotification)
  useEffect(() => {
    onNotificationRef.current = onNotification
  }, [onNotification])
  const pausedRef = useRef(paused)
  useEffect(() => {
    pausedRef.current = paused
  }, [paused])

  useEffect(() => {
    if (!source) return
    return source.subscribeDeltas((delta: Delta) => {
      const item = pillContentFromDelta(delta)
      if (!item || !pillVisibleWhileViewing(item, viewedRef.current)) return
      onNotificationRef.current?.(item)
      if (pausedRef.current) return
      const id = nextIdRef.current++
      const orbState = orbStateForRef.current(item.agent)
      setQueue((current) => enqueuePillNotification(current, { ...item, id, orbState }))
    })
  }, [source])

  useEffect(() => {
    if (queue.length === 0) return
    const timer = setTimeout(() => {
      setQueue((current) => current.slice(1))
    }, PILL_SHOW_MS)
    return () => {
      clearTimeout(timer)
    }
  }, [queue])

  // Visibility is derived at render: a head the user navigated into (their
  // agent's own message) hides instantly and expires on the advance timer.
  const head = queue[0] ?? null
  const current = head && pillVisibleWhileViewing(head, viewedAgent) ? head : null

  return {
    current,
    dismiss: () => {
      setQueue((queued) => queued.slice(1))
    },
  }
}
