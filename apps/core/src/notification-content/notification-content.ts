// Pure parsing for a notification's stored summary, extracted from web's NotificationRow so
// web and mobile render the same body. The stored summary is
// `<notification source=… type=…>INNER</notification>` (see Notification.format_for_display in
// the agent's core/models.py); callers already show source/type/sender separately, so the body
// just needs INNER, optionally split into fields.

// Unwrap the `<notification …>INNER</notification>` envelope to INNER. Falls back to the whole
// string if the shape ever changes.
export function notificationContent(summary: string): string {
  const open = summary.indexOf(">")
  const close = summary.lastIndexOf("</notification>")
  if (open === -1 || close === -1 || close <= open) return summary
  return summary.slice(open + 1, close).trim()
}

// Notification bodies often arrive as `key=value, key=value` — and a value can itself
// contain commas (e.g. a message). A key boundary is a `\w+=` at the start or right after
// `, `; scan each boundary and take the value up to the next one, so a comma inside a value
// isn't mistaken for a separator. Linear (no backtracking). Returns [] for plain text.
export function parseFields(content: string): { key: string; value: string }[] {
  const fields: { key: string; value: string }[] = []
  const keyRe = /(?:^|,\s*)(\w+)=/g
  let match = keyRe.exec(content)
  while (match) {
    const key = match[1] ?? ""
    const valueStart = keyRe.lastIndex
    const next = keyRe.exec(content)
    fields.push({
      key,
      value: content.slice(valueStart, next ? next.index : content.length).trim(),
    })
    match = next
  }
  return fields
}

// The backend renders a notification either as plain prose (its `body`) or, when it has
// no body, as `key=value, …` of its fields — which always starts with a key. So content is
// structured exactly when it starts with `key=`.
export function isStructured(content: string): boolean {
  return /^\w+=/.test(content)
}
