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

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : null
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
