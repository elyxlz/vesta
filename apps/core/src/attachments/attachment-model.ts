// The shared attachment model: the wire metadata shape the app-chat service embeds on user/chat
// events, the client-side sizing/retry constants of the chunked upload protocol, and the one owner
// of kind derivation and byte formatting so every surface renders the same answer.

export interface ChatAttachment {
  id: string
  name: string
  mime: string
  size: number
  width?: number
  height?: number
  duration_secs?: number
}

export type AttachmentKind = "image" | "video" | "audio" | "file"

// Server caps (mirrored from the app-chat service).
export const MAX_ATTACHMENT_BYTES = 512 * 1024 * 1024
export const MAX_ATTACHMENTS_PER_MESSAGE = 10
// The server rejects a single data PUT above this; the adaptive sizer never exceeds it.
export const MAX_CHUNK_UPLOAD_BYTES = 8 * 1024 * 1024

// Adaptive chunk sizing: start modest, double after a fast chunk, halve after a failure, so a fast
// link approaches streaming throughput while a bad link shrinks its loss window.
export const INITIAL_CHUNK_BYTES = 1024 * 1024
export const MIN_CHUNK_BYTES = 256 * 1024
export const CHUNK_FAST_MS = 2_000

// A chunk PUT that produces no response inside this window is aborted and retried smaller; 256 KiB
// in two minutes holds down to roughly 2G speeds.
export const CHUNK_TIMEOUT_MS = 120_000

// Retryable failures back off within these bounds and never give up while the draft lives.
export const RETRY_BASE_MS = 1_000
export const RETRY_MAX_MS = 30_000

export function attachmentKind(mime: string): AttachmentKind {
  if (mime.startsWith("image/")) return "image"
  if (mime.startsWith("video/")) return "video"
  if (mime.startsWith("audio/")) return "audio"
  return "file"
}

// One formatter behind chips, footers, bubbles, and the viewer, matching the agent-side rendering.
export function formatBytes(size: number): string {
  if (size < 1024) return `${String(size)} B`
  let value = size
  for (const unit of ["kB", "MB", "GB"]) {
    value /= 1024
    if (value < 1024 || unit === "GB") return `${value.toFixed(1)} ${unit}`
  }
  return `${String(size)} B`
}

// The service subpaths behind vestad's per-agent proxy. Apps stamp auth themselves (authedUrl for
// media elements, the header-authed client for downloads).
export function appChatAttachmentPath(agent: string, id: string, download = false): string {
  const base = `/agents/${encodeURIComponent(agent)}/app-chat/attachments/${encodeURIComponent(id)}`
  return download ? `${base}?download=1` : base
}
