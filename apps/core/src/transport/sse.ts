import type { FetchLike } from "./http"

export type StreamEvent =
  { kind: "line"; text: string } | { kind: "end" } | { kind: "error"; message: string }

export interface SseDeps {
  fetch: FetchLike
  url: string
  stoppedEvent: string
  token?: () => string | null
}

export interface SseHandle {
  cancel: () => void
}

export function readSse(deps: SseDeps, onEvent: (event: StreamEvent) => void): SseHandle {
  let cancelled = false
  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null
  const isCancelled = (): boolean => cancelled

  const requestHeaders = new Headers()
  const token = deps.token?.()
  if (typeof token === "string") requestHeaders.set("Authorization", `Bearer ${token}`)

  const fail = (message: string): void => {
    if (cancelled) return
    cancelled = true
    onEvent({ kind: "error", message })
  }

  // Parse one SSE block: join its data lines, honor the caller's stopped event
  // as end, and map an "error:"-prefixed payload to an error event.
  const dispatch = (block: string): boolean => {
    let name = "message"
    const data: string[] = []
    for (const line of block.split("\n")) {
      if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""))
      else if (line.startsWith("event:")) name = line.slice(6).trim()
    }
    if (name === deps.stoppedEvent) {
      cancelled = true
      onEvent({ kind: "end" })
      return true
    }
    const text = data.join("\n")
    onEvent(text.startsWith("error:") ? { kind: "error", message: text } : { kind: "line", text })
    return false
  }

  const pump = async (): Promise<void> => {
    let response: Response
    try {
      response = await deps.fetch(deps.url, { headers: requestHeaders })
    } catch {
      fail("log stream disconnected")
      return
    }
    if (isCancelled()) return
    if (!response.ok || !response.body) {
      fail("log stream disconnected")
      return
    }
    reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""
    try {
      for (;;) {
        const chunk = await reader.read()
        if (isCancelled()) return
        if (chunk.done) {
          onEvent({ kind: "end" })
          return
        }
        buffer += decoder.decode(chunk.value, { stream: true })
        let index = buffer.indexOf("\n\n")
        while (index !== -1) {
          const block = buffer.slice(0, index)
          buffer = buffer.slice(index + 2)
          if (dispatch(block)) return
          index = buffer.indexOf("\n\n")
        }
      }
    } catch {
      fail("log stream disconnected")
    }
  }

  void pump()

  return {
    cancel: () => {
      cancelled = true
      if (reader) void reader.cancel()
    },
  }
}
