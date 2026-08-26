import { record } from "../protocol/parse"
import type { HttpClient } from "../transport/http"
import type { PillContent } from "./notifications-pill"

// The durable user-notification history behind the ephemeral delta: vestad logs
// every delivered notification and serves it at GET /notifications, newest
// first, id-cursored. A feed renders a page of these and joins the live
// `user_notification` edge on top; `before` walks arbitrarily far back.

export interface LoggedUserNotification extends PillContent {
  id: number
  /** Unix seconds at delivery. */
  at: number
}

export async function fetchUserNotifications(
  http: HttpClient,
  options: { before?: number; limit?: number } = {},
): Promise<LoggedUserNotification[]> {
  const params = new URLSearchParams()
  if (options.before !== undefined) params.set("before", String(options.before))
  if (options.limit !== undefined) params.set("limit", String(options.limit))
  // params.toString(), not params.size: RN's Hermes URLSearchParams lacks `size`.
  const query = params.toString()
  const body = await http.json<{ notifications?: unknown }>(
    `/notifications${query ? `?${query}` : ""}`,
  )
  return parseLogged(body.notifications)
}

// The awareness-feed seen model, shared by every view: one gateway-synced watermark
// (`userNotificationsSeenAt` on the gateway branch), everything stamped after it unseen.

/** Split a newest-first page on the watermark: what the user has not caught up on, then the rest. */
export function splitBySeen(
  entries: LoggedUserNotification[],
  seenAt: number,
): { unseen: LoggedUserNotification[]; seen: LoggedUserNotification[] } {
  const unseen: LoggedUserNotification[] = []
  const seen: LoggedUserNotification[] = []
  for (const entry of entries) {
    ;(entry.at > seenAt ? unseen : seen).push(entry)
  }
  return { unseen, seen }
}

/** Whether anything arrived past the watermark, from the gateway branch's two scalars alone. */
export function feedHasUnseen(
  lastAt: number | null | undefined,
  seenAt: number | undefined,
): boolean {
  return (lastAt ?? 0) > (seenAt ?? 0)
}

/**
 * Tell the gateway the user caught up on the feed (a history surface closed having offered
 * everything unseen). The server stamps the watermark with its own clock and fans the updated
 * gateway branch to every device, so the client never computes "now" itself.
 */
export async function markUserNotificationsSeen(http: HttpClient): Promise<void> {
  await http.request("/notifications/seen", { method: "POST" })
}

// Parse at the boundary: an entry missing any field is dropped, never rendered
// half-shaped, and an unknown extra field is ignored (additive evolution).
function parseLogged(value: unknown): LoggedUserNotification[] {
  if (!Array.isArray(value)) return []
  const parsed: LoggedUserNotification[] = []
  for (const raw of value) {
    const entry = record(raw)
    if (!entry) continue
    const { id, at, agent, kind, title, body } = entry
    if (typeof id !== "number" || typeof at !== "number") continue
    if (typeof agent !== "string" || typeof kind !== "string") continue
    if (typeof title !== "string" || typeof body !== "string") continue
    parsed.push({ id, at, agent, kind, title, body })
  }
  return parsed
}
