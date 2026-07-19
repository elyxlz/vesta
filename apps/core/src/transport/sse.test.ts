import { describe, expect, it, vi } from "vitest"

import { readSse } from "./sse"
import type { SseDeps, StreamEvent } from "./sse"
import type { FetchLike } from "./http"

function fetchReturning(body: string, status = 200): FetchLike {
  return vi.fn<FetchLike>().mockResolvedValue(new Response(body, { status }))
}

async function collect(deps: SseDeps): Promise<StreamEvent[]> {
  const events: StreamEvent[] = []
  readSse(deps, (event) => events.push(event))
  await vi.waitFor(() => {
    const last = events.at(-1)
    expect(last?.kind === "end" || last?.kind === "error").toBe(true)
  })
  return events
}

describe("readSse", () => {
  it("emits line events for data blocks then end on the stopped event", async () => {
    const events = await collect({
      fetch: fetchReturning("data: hello\n\ndata: world\n\nevent: logs_stopped\ndata: \n\n"),
      url: "https://vestad.test/logs",
      stoppedEvent: "logs_stopped",
    })
    expect(events).toEqual([
      { kind: "line", text: "hello" },
      { kind: "line", text: "world" },
      { kind: "end" },
    ])
  })

  it("maps error-prefixed data to an error event", async () => {
    const events = await collect({
      fetch: fetchReturning("data: error: boom\n\nevent: logs_stopped\ndata: \n\n"),
      url: "https://vestad.test/logs",
      stoppedEvent: "logs_stopped",
    })
    expect(events).toEqual([{ kind: "error", message: "error: boom" }, { kind: "end" }])
  })

  it("reports a transport error when the response is not ok", async () => {
    const events = await collect({
      fetch: fetchReturning("nope", 500),
      url: "https://vestad.test/logs",
      stoppedEvent: "logs_stopped",
    })
    expect(events).toEqual([{ kind: "error", message: "log stream disconnected" }])
  })

  it("reports a transport error when fetch rejects", async () => {
    const events = await collect({
      fetch: vi.fn<FetchLike>().mockRejectedValue(new Error("down")),
      url: "https://vestad.test/logs",
      stoppedEvent: "logs_stopped",
    })
    expect(events).toEqual([{ kind: "error", message: "log stream disconnected" }])
  })

  it("emits end when the stream closes without a stopped event", async () => {
    const events = await collect({
      fetch: fetchReturning("data: only\n\n"),
      url: "https://vestad.test/logs",
      stoppedEvent: "logs_stopped",
    })
    expect(events).toEqual([{ kind: "line", text: "only" }, { kind: "end" }])
  })
})
