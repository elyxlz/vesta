import { describe, expect, it } from "vitest"

import { createChatSocket } from "./chat-socket"
import type { ChatSocketState } from "./chat-socket"
import type { ChatMessage } from "./chat-stream-model"
import type { SocketLike } from "../transport/socket"

class FakeSocket implements SocketLike {
  onopen: (() => void) | null = null
  onmessage: ((data: string) => void) | null = null
  onclose: (() => void) | null = null
  closed = false
  send(): void {
    // The chat socket is read-only; nothing is ever sent.
  }
  close(): void {
    this.closed = true
  }
}

interface Harness {
  sockets: FakeSocket[]
  urls: string[]
  timers: { fn: () => void; ms: number }[]
  states: ChatSocketState[]
  events: ChatMessage[]
  deps: Parameters<typeof createChatSocket>[0]
}

function harness(): Harness {
  const sockets: FakeSocket[] = []
  const urls: string[] = []
  const timers: { fn: () => void; ms: number }[] = []
  const states: ChatSocketState[] = []
  const events: ChatMessage[] = []
  let builds = 0
  const deps = {
    // A fresh credential per attempt, as the real builder refreshes the token: the counter makes
    // it observable that the URL is re-derived rather than captured once.
    buildUrl: () => {
      builds += 1
      return Promise.resolve(`wss://vestad.test/agents/ada/app-chat/ws?token=key-${String(builds)}`)
    },
    createSocket: (url: string) => {
      urls.push(url)
      const socket = new FakeSocket()
      sockets.push(socket)
      return socket
    },
    setTimer: (fn: () => void, ms: number) => {
      timers.push({ fn, ms })
      return timers.length - 1
    },
    clearTimer: () => undefined,
  }
  return { sockets, urls, timers, states, events, deps }
}

// The URL builder is async, so the socket is created a microtask after createChatSocket returns.
async function flush(): Promise<void> {
  for (let i = 0; i < 5; i++) await Promise.resolve()
}

async function start(h: Harness): Promise<ReturnType<typeof createChatSocket>> {
  const socket = createChatSocket(h.deps, {
    onEvent: (event) => h.events.push(event),
    onStateChange: (state) => h.states.push(state),
  })
  await flush()
  return socket
}

describe("createChatSocket", () => {
  it("reports connecting then open", async () => {
    const h = harness()
    await start(h)
    expect(h.states).toEqual(["connecting"])
    h.sockets[0]?.onopen?.()
    expect(h.states).toEqual(["connecting", "open"])
  })

  it("delivers each inbound JSON frame as a ChatMessage", async () => {
    const h = harness()
    await start(h)
    h.sockets[0]?.onopen?.()
    h.sockets[0]?.onmessage?.(JSON.stringify({ type: "chat", text: "hi", id: 7 }))
    expect(h.events).toEqual([{ type: "chat", text: "hi", id: 7 }])
  })

  it("ignores malformed JSON", async () => {
    const h = harness()
    await start(h)
    h.sockets[0]?.onopen?.()
    h.sockets[0]?.onmessage?.("not json")
    expect(h.events).toEqual([])
  })

  it("reconnects after a close and re-signals open (the reseed trigger)", async () => {
    const h = harness()
    await start(h)
    h.sockets[0]?.onopen?.()
    h.sockets[0]?.onclose?.()
    expect(h.states).toEqual(["connecting", "open", "reconnecting"])
    expect(h.timers).toHaveLength(1)
    h.timers[0]?.fn()
    await flush()
    h.sockets[1]?.onopen?.()
    expect(h.states).toEqual(["connecting", "open", "reconnecting", "connecting", "open"])
  })

  it("does not reconnect after close() is terminal", async () => {
    const h = harness()
    const socket = await start(h)
    h.sockets[0]?.onopen?.()
    socket.close()
    expect(h.states.at(-1)).toBe("closed")
    expect(h.sockets[0]?.closed).toBe(true)
    h.sockets[0]?.onclose?.()
    expect(h.timers).toHaveLength(0)
  })

  // The credential rides in the URL, so a reconnect hours after mount must re-derive it. Capturing
  // one URL at construction would dial the reconnect with a key that expired in the meantime.
  it("re-derives the url on every reconnect", async () => {
    const h = harness()
    await start(h)
    h.sockets[0]?.onopen?.()
    h.sockets[0]?.onclose?.()
    h.timers[0]?.fn()
    await flush()

    expect(h.urls).toEqual([
      "wss://vestad.test/agents/ada/app-chat/ws?token=key-1",
      "wss://vestad.test/agents/ada/app-chat/ws?token=key-2",
    ])
  })

  it("keeps reconnecting through a streak of pre-open closes", async () => {
    const h = harness()
    await start(h)
    h.sockets[0]?.onclose?.()
    h.timers[0]?.fn()
    await flush()
    h.sockets[1]?.onclose?.()
    h.timers[1]?.fn()
    await flush()

    expect(h.sockets).toHaveLength(3)
    expect(h.states).toEqual([
      "connecting",
      "reconnecting",
      "connecting",
      "reconnecting",
      "connecting",
    ])
  })

  it("schedules a reconnect when the url builder rejects", async () => {
    const h = harness()
    h.deps.buildUrl = () => Promise.reject(new Error("not connected"))
    await start(h)
    expect(h.states).toEqual(["connecting", "reconnecting"])
    expect(h.sockets).toHaveLength(0)
    expect(h.timers).toHaveLength(1)
  })
})
