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
  advanceTimers: () => Promise<void>
}

function harness(): Harness {
  const sockets: FakeSocket[] = []
  const timers: { fn: () => void; ms: number }[] = []
  const states: SyncState[] = []
  const snapshots: Tree[] = []
  const deltas: Delta[] = []
  let fired = 0
  const deps: SyncSocketDeps = {
    buildUrl: () => Promise.resolve("wss://vestad.test/sync"),
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
    clientKind: "web",
  }
  const advanceTimers = async (): Promise<void> => {
    while (fired < timers.length) {
      timers[fired++]?.fn()
    }
    await flush()
  }
  return { sockets, timers, states, snapshots, deltas, deps, advanceTimers }
}

// The URL builder is async, so the socket is created a microtask after createSyncSocket returns.
async function flush(): Promise<void> {
  for (let i = 0; i < 5; i++) await Promise.resolve()
}

async function start(h: Harness): Promise<ReturnType<typeof createSyncSocket>> {
  const socket = createSyncSocket(h.deps, {
    onStateChange: (state) => h.states.push(state),
    onSnapshot: (tree) => h.snapshots.push(tree),
    onDelta: (delta) => h.deltas.push(delta),
  })
  await flush()
  return socket
}

function hello(version: string, minSupported: string): string {
  return JSON.stringify({ type: "hello", version, min_supported: minSupported })
}

describe("createSyncSocket", () => {
  it("waits for the url builder before opening a socket", async () => {
    const h = harness()
    let release = (): void => undefined
    h.deps.buildUrl = async () => {
      await new Promise<void>((resolve) => {
        release = resolve
      })
      return "wss://vestad.test/sync"
    }
    // The builder refreshes an expiring token, so nothing may be dialled until it resolves:
    // otherwise a client waking from sleep presents the token that expired while it was away.
    await start(h)
    expect(h.sockets).toHaveLength(0)
    release()
    await flush()
    expect(h.sockets).toHaveLength(1)
  })

  it("schedules a reconnect when the url builder rejects", async () => {
    const h = harness()
    h.deps.buildUrl = () => Promise.reject(new Error("not connected"))
    await start(h)
    expect(h.states).toEqual(["connecting", "reconnecting"])
    expect(h.sockets).toHaveLength(0)
    expect(h.timers).toHaveLength(1)
  })

  it("reports connecting then open", async () => {
    const h = harness()
    await start(h)
    expect(h.states).toEqual(["connecting"])
    h.sockets[0]?.onopen?.()
    expect(h.states).toEqual(["connecting", "open"])
  })

  it("delivers snapshot and delta callbacks", async () => {
    const h = harness()
    await start(h)
    const socket = h.sockets[0]
    socket?.onopen?.()
    socket?.onmessage?.(JSON.stringify({ type: "snapshot", tree: { gateway: {}, agents: {} } }))
    socket?.onmessage?.(JSON.stringify({ type: "notifications", agent: "scout", pending: [] }))
    expect(h.snapshots).toHaveLength(1)
    expect(h.deltas).toEqual([{ type: "notifications", agent: "scout", pending: [] }])
  })

  it("ignores unknown frames", async () => {
    const h = harness()
    await start(h)
    h.sockets[0]?.onmessage?.(JSON.stringify({ type: "mystery" }))
    expect(h.snapshots).toHaveLength(0)
    expect(h.deltas).toHaveLength(0)
  })

  it("enters the terminal app_behind state below the served minimum", async () => {
    const h = harness()
    await start(h)
    const socket = h.sockets[0]
    socket?.onopen?.()
    socket?.onmessage?.(hello("0.2.0", "0.2.0"))
    expect(h.states.at(-1)).toBe("app_behind")
    expect(socket?.closed).toBe(true)
    socket?.onclose?.()
    expect(h.timers).toHaveLength(0)
  })

  it("enters the recoverable gateway_behind state when ahead of the gateway", async () => {
    const h = harness()
    await start(h)
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

  it("grows the reconnect backoff from 1s toward the cap", async () => {
    const h = harness()
    await start(h)
    h.sockets[0]?.onclose?.()
    h.timers[0]?.fn()
    await flush()
    h.sockets[1]?.onclose?.()
    expect(h.timers.map((timer) => timer.ms)).toEqual([1000, 2000])
  })

  it("resets the backoff after a successful open", async () => {
    const h = harness()
    await start(h)
    h.sockets[0]?.onclose?.()
    h.timers[0]?.fn()
    await flush()
    h.sockets[1]?.onopen?.()
    h.sockets[1]?.onclose?.()
    expect(h.timers.map((timer) => timer.ms)).toEqual([1000, 1000])
  })

  it("sends a reauth frame without reconnecting", async () => {
    const h = harness()
    const sync = await start(h)
    h.sockets[0]?.onopen?.()
    sync.reauth("fresh")
    expect(h.sockets[0]?.sent).toEqual([JSON.stringify({ type: "reauth", token: "fresh" })])
  })

  it("sends client_context on reportPresence when open", async () => {
    const h = harness()
    const socket = await start(h)
    h.sockets[0]?.onopen?.()
    socket.reportPresence(true)
    // A genuine report is not a resync, so vestad may treat it as a return to focus.
    expect(h.sockets[0]?.sent).toContainEqual(
      JSON.stringify({
        type: "client_context",
        focused: true,
        client: "web",
        resync: false,
        viewing: null,
      }),
    )
  })

  it("sends the open agent on reportViewing, alongside cached focus", async () => {
    const h = harness()
    const socket = await start(h)
    h.sockets[0]?.onopen?.()
    socket.reportPresence(true)
    socket.reportViewing("scout")
    // The viewing report carries the cached focus too, so vestad sees both in one context frame.
    expect(h.sockets[0]?.sent).toContainEqual(
      JSON.stringify({
        type: "client_context",
        focused: true,
        client: "web",
        resync: false,
        viewing: "scout",
      }),
    )
  })

  it("sends a report issued while connecting as a fresh focus once open", async () => {
    const h = harness()
    const socket = await start(h)
    // Every client reports from a mount effect, so the very first report always lands before the
    // handshake completes. It is still the user arriving, so it must not be downgraded to a resync.
    socket.reportPresence(true)
    expect(h.sockets[0]?.sent).toEqual([])
    h.sockets[0]?.onopen?.()
    expect(h.sockets[0]?.sent).toEqual([
      JSON.stringify({
        type: "client_context",
        focused: true,
        client: "web",
        resync: false,
        viewing: null,
      }),
    ])
  })

  it("skips a repeat report of the current focus", async () => {
    const h = harness()
    const socket = await start(h)
    h.sockets[0]?.onopen?.()
    socket.reportPresence(true)
    socket.reportPresence(true)
    expect(h.sockets[0]?.sent).toHaveLength(1)
  })

  it("sends a reauth issued while connecting once open", async () => {
    const h = harness()
    const sync = await start(h)
    // The mount-time refresh reauths before the handshake completes. The gateway armed this
    // session's deadline from the connect token, so dropping the frame would expire a live socket.
    sync.reauth("fresh")
    expect(h.sockets[0]?.sent).toEqual([])
    h.sockets[0]?.onopen?.()
    expect(h.sockets[0]?.sent).toEqual([JSON.stringify({ type: "reauth", token: "fresh" })])
  })

  it("re-sends the last context on reconnect as a resync", async () => {
    const h = harness()
    const socket = await start(h)
    h.sockets[0]?.onopen?.()
    socket.reportPresence(true)
    h.sockets[0]?.onclose?.()
    await h.advanceTimers()
    h.sockets[1]?.onopen?.()
    // The reconnect replay carries resync:true so it isn't mistaken for a fresh focus.
    expect(h.sockets[1]?.sent).toContainEqual(
      JSON.stringify({
        type: "client_context",
        focused: true,
        client: "web",
        resync: true,
        viewing: null,
      }),
    )
  })

  it("does not reconnect after close", async () => {
    const h = harness()
    const sync = await start(h)
    h.sockets[0]?.onopen?.()
    sync.close()
    expect(h.states.at(-1)).toBe("closed")
    h.sockets[0]?.onclose?.()
    expect(h.timers).toHaveLength(0)
  })
})
