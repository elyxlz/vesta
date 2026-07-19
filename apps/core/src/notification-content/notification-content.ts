import type { NotificationEvent } from "../protocol/events"

// Pure parsing for a notification's stored summary, the single owner shared by web and mobile.
// The agent emits `<channel source=… type=… …attrs>INNER</channel>` (see Notification.format_for_display
// in agent/core/notification.py): routing metadata as attributes, the human-readable message as the
// inner body (or a multi-line prose body directly). This splits that envelope into a display-ready
// {headline, body, context}, decoding XML entities and promoting the most useful fields.

// A notification as a view holds it: core's wire shape minus the strict ledger `id`, which the live
// chat stream leaves optional (ChatMessage) and notification display never reads.
export type NotificationView = Omit<NotificationEvent, "id"> & { id?: number }

export interface NotificationContent {
  headline: string
  body: string | null
  context: string | null
}

interface ParsedChannel {
  attributes: Record<string, string>
  body: string
}

const TITLE_FIELDS = ["subject", "title"] as const
const SECONDARY_FIELDS = ["preview", "reason", "description"] as const
const CONTEXT_FIELDS = [
  "channel_name",
  "chat_name",
  "server",
  "account",
  "folder",
  "location",
  "start_time",
  "minutes_until",
  "media_type",
] as const

function decodeXml(value: string): string {
  const named = value
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&apos;", "'")
    .replaceAll("&amp;", "&")
  return named.replace(/&#(x[0-9a-f]+|\d+);/gi, (entity, code: string) => {
    const codePoint = code.toLowerCase().startsWith("x")
      ? Number.parseInt(code.slice(1), 16)
      : Number.parseInt(code, 10)
    return Number.isFinite(codePoint) && codePoint <= 0x10ffff
      ? String.fromCodePoint(codePoint)
      : entity
  })
}

function isSpace(ch: string): boolean {
  return ch === " " || ch === "\t" || ch === "\n" || ch === "\r" || ch === "\f"
}

function isKeyStart(ch: string): boolean {
  return (ch >= "A" && ch <= "Z") || (ch >= "a" && ch <= "z") || ch === "_"
}

function isKeyChar(ch: string): boolean {
  return isKeyStart(ch) || (ch >= "0" && ch <= "9") || ch === "." || ch === "-"
}

// Strictly linear `key="value"` scan over quoteattr output (space-separated, values XML-escaped so
// they never contain a raw delimiter quote). A regex over this grammar backtracks quadratically on a
// long run of name-chars (js/polynomial-redos); a single indexOf-driven pass cannot. Each iteration
// consumes at least one character, so a garbage prefix with no `=` terminates in one sweep.
function parseAttributes(attrText: string): Record<string, string> {
  const attributes: Record<string, string> = {}
  const length = attrText.length
  let cursor = 0
  while (cursor < length) {
    while (isSpace(attrText.charAt(cursor))) cursor++
    if (cursor >= length) break
    const keyStart = cursor
    while (isKeyChar(attrText.charAt(cursor))) cursor++
    const key = attrText.slice(keyStart, cursor)
    while (isSpace(attrText.charAt(cursor))) cursor++
    if (attrText.charAt(cursor) !== "=") {
      if (cursor === keyStart) cursor++
      continue
    }
    cursor++
    while (isSpace(attrText.charAt(cursor))) cursor++
    const quote = attrText.charAt(cursor)
    if (quote !== '"' && quote !== "'") continue
    const valueStart = cursor + 1
    const valueEnd = attrText.indexOf(quote, valueStart)
    if (valueEnd === -1) break
    if (key !== "" && isKeyStart(key.charAt(0))) {
      attributes[key] = decodeXml(attrText.slice(valueStart, valueEnd))
    }
    cursor = valueEnd + 1
  }
  return attributes
}

function parseChannel(summary: string): ParsedChannel | null {
  const match = /^<channel\b([^>]*)>([\s\S]*)<\/channel>$/.exec(summary.trim())
  if (!match) return null

  return {
    attributes: parseAttributes(match[1] ?? ""),
    body: decodeXml(match[2] ?? "").trim(),
  }
}

function takeFirst(fields: Record<string, string>, keys: readonly string[]): string | null {
  for (const key of keys) {
    const value = fields[key]?.trim()
    if (value) return value
  }
  return null
}

function humanize(value: string): string {
  const words = value.replaceAll("_", " ").trim()
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Notification"
}

function contextValue(key: string, value: string): string {
  if (key === "start_time") return `Starts ${value}`
  if (key === "minutes_until") return `${value} min`
  return value
}

export function parseNotificationContent(event: NotificationView): NotificationContent {
  const parsed = parseChannel(event.summary)
  if (!parsed) {
    return {
      headline: event.summary.trim() || humanize(event.notif_type ?? "notification"),
      body: null,
      context: null,
    }
  }

  const fields = { ...parsed.attributes, ...(event.fields ?? {}) }
  const title = takeFirst(fields, TITLE_FIELDS)
  const secondary = parsed.body || takeFirst(fields, SECONDARY_FIELDS)
  const context = CONTEXT_FIELDS.flatMap((key) => {
    const value = fields[key]?.trim()
    return value ? [contextValue(key, value)] : []
  })
  const headline = title ?? secondary ?? humanize(event.notif_type ?? fields.type ?? "notification")

  return {
    headline,
    body: title && secondary && secondary !== title ? secondary : null,
    context: context.length > 0 ? context.join(" · ") : null,
  }
}
