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
  timers: { fn: () => void; ms: number }[]
  states: ChatSocketState[]
  events: ChatMessage[]
  deps: Parameters<typeof createChatSocket>[0]
}

function harness(): Harness {
  const sockets: FakeSocket[] = []
  const timers: { fn: () => void; ms: number }[] = []
  const states: ChatSocketState[] = []
  const events: ChatMessage[] = []
  const deps = {
    buildUrl: () => "wss://vestad.test/agents/ada/app-chat/ws",
    createSocket: () => {
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
  return { sockets, timers, states, events, deps }
}

function start(h: Harness): ReturnType<typeof createChatSocket> {
  return createChatSocket(h.deps, {
    onEvent: (event) => h.events.push(event),
    onStateChange: (state) => h.states.push(state),
  })
}

describe("createChatSocket", () => {
  it("reports connecting then open", () => {
    const h = harness()
    start(h)
    expect(h.states).toEqual(["connecting"])
    h.sockets[0]?.onopen?.()
    expect(h.states).toEqual(["connecting", "open"])
  })

  it("delivers each inbound JSON frame as a ChatMessage", () => {
    const h = harness()
    start(h)
    h.sockets[0]?.onopen?.()
    h.sockets[0]?.onmessage?.(JSON.stringify({ type: "chat", text: "hi", id: 7 }))
    expect(h.events).toEqual([{ type: "chat", text: "hi", id: 7 }])
  })

  it("ignores malformed JSON", () => {
    const h = harness()
    start(h)
    h.sockets[0]?.onopen?.()
    h.sockets[0]?.onmessage?.("not json")
    expect(h.events).toEqual([])
  })

  it("reconnects after a close and re-signals open (the reseed trigger)", () => {
    const h = harness()
    start(h)
    h.sockets[0]?.onopen?.()
    h.sockets[0]?.onclose?.()
    expect(h.states).toEqual(["connecting", "open", "reconnecting"])
    expect(h.timers).toHaveLength(1)
    h.timers[0]?.fn()
    h.sockets[1]?.onopen?.()
    expect(h.states).toEqual(["connecting", "open", "reconnecting", "connecting", "open"])
  })

  it("does not reconnect after close() is terminal", () => {
    const h = harness()
    const socket = start(h)
    h.sockets[0]?.onopen?.()
    socket.close()
    expect(h.states.at(-1)).toBe("closed")
    expect(h.sockets[0]?.closed).toBe(true)
    h.sockets[0]?.onclose?.()
    expect(h.timers).toHaveLength(0)
  })

  it("schedules a reconnect when buildUrl throws", () => {
    const h = harness()
    h.deps.buildUrl = () => {
      throw new Error("not connected")
    }
    start(h)
    expect(h.states).toEqual(["connecting", "reconnecting"])
    expect(h.sockets).toHaveLength(0)
    expect(h.timers).toHaveLength(1)
  })
})
