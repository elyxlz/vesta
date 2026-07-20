import { describe, expect, it } from "vitest"

import { createSyncSocket } from "./socket"
import type { SocketLike, SyncSocketDeps, SyncState } from "./socket"
import type { Delta } from "../protocol/deltas"
import type { Tree } from "../protocol/tree"

class FakeSocket implements SocketLike {
  onopen: (() => void) | null = null
  onmessage: ((data: string) => void) | null = null
  onclose: (() => void) | null = null
  readonly sent: string[] = []
  closed = false
  send(data: string): void {
    this.sent.push(data)
  }
  close(): void {
    this.closed = true
  }
}

interface Harness {
  sockets: FakeSocket[]
  timers: { fn: () => void; ms: number }[]
  states: SyncState[]
  snapshots: Tree[]
  deltas: Delta[]
  deps: SyncSocketDeps
}

function harness(): Harness {
  const sockets: FakeSocket[] = []
  const timers: { fn: () => void; ms: number }[] = []
  const states: SyncState[] = []
  const snapshots: Tree[] = []
  const deltas: Delta[] = []
  const deps: SyncSocketDeps = {
    buildUrl: () => "wss://vestad.test/sync",
    createSocket: () => {
      const socket = new FakeSocket()
      sockets.push(socket)
      return socket
    },
    setTimer: (fn, ms) => {
      timers.push({ fn, ms })
      return timers.length - 1
    },
    clearTimer: () => undefined,
    clientVersion: "0.1.179",
  }
  return { sockets, timers, states, snapshots, deltas, deps }
}

function start(h: Harness): ReturnType<typeof createSyncSocket> {
  return createSyncSocket(h.deps, {
    onStateChange: (state) => h.states.push(state),
    onSnapshot: (tree) => h.snapshots.push(tree),
    onDelta: (delta) => h.deltas.push(delta),
  })
}

function hello(version: string, minSupported: string): string {
  return JSON.stringify({ type: "hello", version, min_supported: minSupported })
}

describe("createSyncSocket", () => {
  it("reports connecting then open", () => {
    const h = harness()
    start(h)
    expect(h.states).toEqual(["connecting"])
    h.sockets[0]?.onopen?.()
    expect(h.states).toEqual(["connecting", "open"])
  })

  it("delivers snapshot and delta callbacks", () => {
    const h = harness()
    start(h)
    const socket = h.sockets[0]
    socket?.onopen?.()
    socket?.onmessage?.(JSON.stringify({ type: "snapshot", tree: { gateway: {}, agents: {} } }))
    socket?.onmessage?.(JSON.stringify({ type: "notifications", agent: "scout", pending: [] }))
    expect(h.snapshots).toHaveLength(1)
    expect(h.deltas).toEqual([{ type: "notifications", agent: "scout", pending: [] }])
  })

  it("ignores unknown frames", () => {
    const h = harness()
    start(h)
    h.sockets[0]?.onmessage?.(JSON.stringify({ type: "mystery" }))
    expect(h.snapshots).toHaveLength(0)
    expect(h.deltas).toHaveLength(0)
  })

  it("enters the terminal app_behind state below the served minimum", () => {
    const h = harness()
    start(h)
    const socket = h.sockets[0]
    socket?.onopen?.()
    socket?.onmessage?.(hello("0.2.0", "0.2.0"))
    expect(h.states.at(-1)).toBe("app_behind")
    expect(socket?.closed).toBe(true)
    socket?.onclose?.()
    expect(h.timers).toHaveLength(0)
  })

  it("enters the recoverable gateway_behind state when ahead of the gateway", () => {
    const h = harness()
    start(h)
    const socket = h.sockets[0]
    socket?.onopen?.()
    socket?.onmessage?.(hello("0.0.1", "0.0.0"))
    expect(h.states.at(-1)).toBe("gateway_behind")
    // Recoverable: the socket stays live and a later close reconnects, so it self-heals once the
    // gateway restarts newer (its reconnect backoff is the retry cadence).
    expect(socket?.closed).toBe(false)
    socket?.onclose?.()
    expect(h.timers).toHaveLength(1)
  })

  it("grows the reconnect backoff from 1s toward the cap", () => {
    const h = harness()
    start(h)
    h.sockets[0]?.onclose?.()
    h.timers[0]?.fn()
    h.sockets[1]?.onclose?.()
    expect(h.timers.map((timer) => timer.ms)).toEqual([1000, 2000])
  })

  it("resets the backoff after a successful open", () => {
    const h = harness()
    start(h)
    h.sockets[0]?.onclose?.()
    h.timers[0]?.fn()
    h.sockets[1]?.onopen?.()
    h.sockets[1]?.onclose?.()
    expect(h.timers.map((timer) => timer.ms)).toEqual([1000, 1000])
  })

  it("sends a reauth frame without reconnecting", () => {
    const h = harness()
    const sync = start(h)
    h.sockets[0]?.onopen?.()
    sync.reauth("fresh")
    expect(h.sockets[0]?.sent).toEqual([JSON.stringify({ type: "reauth", token: "fresh" })])
  })

  it("does not reconnect after close", () => {
    const h = harness()
    const sync = start(h)
    h.sockets[0]?.onopen?.()
    sync.close()
    expect(h.states.at(-1)).toBe("closed")
    h.sockets[0]?.onclose?.()
    expect(h.timers).toHaveLength(0)
  })
})
