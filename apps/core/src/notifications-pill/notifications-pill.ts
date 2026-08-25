import type { Delta } from "../protocol/deltas"
import type { OrbVisualState } from "../agent-status/agent-status"

// The shared, view-independent model of the navbar notifications pill: the
// queue, grouping, timing, and icon vocabulary live here, and a view owns only
// its platform's rendering.

/** How long one notification holds the pill before the queue advances. */
export const PILL_SHOW_MS = 2500

export interface PillContent {
  agent: string
  kind: string
  title: string
  body: string
}

/**
 * One queued pill notification: the id keys one displayed notification for the
 * rotary slide, and the orb state is the named agent's status snapshotted when
 * the notification was taken in, so what the pill shows is what the agent
 * looked like at that moment.
 */
export interface PillNotification extends PillContent {
  id: number
  orbState: OrbVisualState | null
}

/**
 * The standardized icon per notification kind, as lucide icon names: each app
 * resolves the name to its own icon component (lucide-react on web,
 * lucide-react-native on mobile). The leading glyph says what happened; the
 * orb, when the notification names a roster agent, says who. An unknown kind
 * takes `PILL_FALLBACK_ICON`, matching the render-anyway rule.
 */
export const PILL_KIND_ICONS: Record<string, string> = {
  message: "message-square",
  needs_user: "circle-alert",
  // LEGACY(remove-when: no supported gateway emits kind=rate_limited; it was
  // renamed needs_user in the release carrying the durable notification log):
  rate_limited: "circle-alert",
  task: "square-check",
  agent_status: "activity",
  gateway_updated: "sparkles",
  update_available: "circle-arrow-up",
  device_connected: "monitor-smartphone",
}
export const PILL_FALLBACK_ICON = "bell"

/** A message from the agent whose page is open never shows: the chat renders it. */
export function pillVisibleWhileViewing(item: PillContent, viewedAgent: string | null): boolean {
  return item.kind !== "message" || item.agent !== viewedAgent
}

/**
 * Insert after the last queued item of the same kind, so pending notifications
 * cluster by kind: the pill rotates through one kind per open, and a late
 * arrival of a kind already pending joins its group instead of splitting it.
 */
export function enqueuePillNotification(
  queue: PillNotification[],
  item: PillNotification,
): PillNotification[] {
  for (let index = queue.length - 1; index >= 0; index--) {
    if (queue[index]?.kind === item.kind) {
      return [...queue.slice(0, index + 1), item, ...queue.slice(index + 1)]
    }
  }
  return [...queue, item]
}

/** The `user_notification` payload as a pill item, or null for any other delta. */
export function pillContentFromDelta(delta: Delta): PillContent | null {
  if (delta.type !== "user_notification") return null
  const { agent, kind, title, body } = delta
  return { agent, kind, title, body }
}
