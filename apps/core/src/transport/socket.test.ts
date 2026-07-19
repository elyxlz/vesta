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

function hello(floor: number, protocol: number): string {
  return JSON.stringify({ type: "hello", version: "0.2.0", protocol, floor })
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
    socket?.onmessage?.(JSON.stringify({ type: "resync", agent: "scout" }))
    expect(h.snapshots).toHaveLength(1)
    expect(h.deltas).toEqual([{ type: "resync", agent: "scout" }])
  })

  it("ignores unknown frames", () => {
    const h = harness()
    start(h)
    h.sockets[0]?.onmessage?.(JSON.stringify({ type: "mystery" }))
    expect(h.snapshots).toHaveLength(0)
    expect(h.deltas).toHaveLength(0)
  })

  it("enters the terminal incompatible state below floor", () => {
    const h = harness()
    start(h)
    const socket = h.sockets[0]
    socket?.onopen?.()
    socket?.onmessage?.(hello(2, 2))
    expect(h.states.at(-1)).toBe("incompatible")
    expect(socket?.closed).toBe(true)
    socket?.onclose?.()
    expect(h.timers).toHaveLength(0)
  })

  it("replays desired watches on reconnect", () => {
    const h = harness()
    const sync = start(h)
    h.sockets[0]?.onopen?.()
    sync.watch("scout")
    expect(h.sockets[0]?.sent).toEqual([JSON.stringify({ type: "watch", agent: "scout" })])
    h.sockets[0]?.onclose?.()
    expect(h.timers).toHaveLength(1)
    h.timers[0]?.fn()
    h.sockets[1]?.onopen?.()
    expect(h.sockets[1]?.sent).toEqual([JSON.stringify({ type: "watch", agent: "scout" })])
  })

  it("drops a watch when its agent is removed", () => {
    const h = harness()
    const sync = start(h)
    h.sockets[0]?.onopen?.()
    sync.watch("scout")
    h.sockets[0]?.onmessage?.(JSON.stringify({ type: "agent_removed", name: "scout" }))
    h.sockets[0]?.onclose?.()
    h.timers[0]?.fn()
    h.sockets[1]?.onopen?.()
    expect(h.sockets[1]?.sent).toEqual([])
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
