import { describe, expect, it, vi } from "vitest"

import { createController } from "./controller"
import type { SocketLike } from "../transport/socket"
import type { Delta } from "../protocol/deltas"
import type { GatewayInfo, Tree } from "../protocol/tree"

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

function baseGateway(): GatewayInfo {
  return {
    version: "0.2.0",
    channel: "stable",
    autoUpdate: true,
    port: 4111,
    lan: { exposed: false, url: null },
    tunnelUrl: null,
    updateAvailable: false,
    latestVersion: null,
    managed: false,
  }
}

function baseTree(): Tree {
  return { gateway: baseGateway(), agents: {} }
}

interface Harness {
  sockets: FakeSocket[]
  controller: ReturnType<typeof createController>
}

function harness(): Harness {
  const sockets: FakeSocket[] = []
  const controller = createController({
    sync: {
      buildUrl: () => "wss://vestad.test/sync",
      createSocket: () => {
        const socket = new FakeSocket()
        sockets.push(socket)
        return socket
      },
      setTimer: () => 0,
      clearTimer: () => undefined,
    },
    http: {
      baseUrl: () => "https://vestad.test",
      fetch: () => Promise.resolve(new Response(null, { status: 200 })),
      token: () => null,
      refresh: () => Promise.resolve(false),
    },
  })
  return { sockets, controller }
}

function hello(floor: number, protocol: number): string {
  return JSON.stringify({ type: "hello", version: "0.2.0", protocol, floor })
}

describe("createController", () => {
  it("populates the replica from a hello then a snapshot", () => {
    const h = harness()
    const socket = h.sockets[0]
    socket?.onopen?.()
    socket?.onmessage?.(hello(1, 1))
    expect(h.controller.replica.getState()).toBeNull()
    socket?.onmessage?.(JSON.stringify({ type: "snapshot", tree: baseTree() }))
    expect(h.controller.replica.getState()?.gateway.port).toBe(4111)
  })

  it("reduces a delta into the replica", () => {
    const h = harness()
    const socket = h.sockets[0]
    socket?.onopen?.()
    socket?.onmessage?.(JSON.stringify({ type: "snapshot", tree: baseTree() }))
    const value: GatewayInfo = { ...baseGateway(), version: "0.3.0", updateAvailable: true }
    socket?.onmessage?.(JSON.stringify({ type: "state", scope: "gateway", value }))
    expect(h.controller.replica.getState()?.gateway.version).toBe("0.3.0")
    expect(h.controller.replica.getState()?.gateway.updateAvailable).toBe(true)
  })

  it("exposes connection state through getSyncState and subscribeSyncState", () => {
    const h = harness()
    const listener = vi.fn()
    h.controller.subscribeSyncState(listener)
    expect(h.controller.getSyncState()).toBe("connecting")
    h.sockets[0]?.onopen?.()
    expect(h.controller.getSyncState()).toBe("open")
    expect(listener).toHaveBeenCalled()
  })

  it("stops notifying sync-state listeners after unsubscribe", () => {
    const h = harness()
    const listener = vi.fn()
    const off = h.controller.subscribeSyncState(listener)
    off()
    h.sockets[0]?.onopen?.()
    expect(listener).not.toHaveBeenCalled()
  })

  it("fans out every delta to subscribeDeltas, including the user_notification the reducer ignores", () => {
    const h = harness()
    const seen: Delta[] = []
    h.controller.subscribeDeltas((delta) => seen.push(delta))
    const socket = h.sockets[0]
    socket?.onopen?.()
    socket?.onmessage?.(JSON.stringify({ type: "snapshot", tree: baseTree() }))
    const userNotification: Delta = {
      type: "user_notification",
      agent: "scout",
      kind: "message",
      title: "scout",
      body: "hi",
    }
    socket?.onmessage?.(JSON.stringify(userNotification))
    expect(seen).toEqual([userNotification])
    // The user notification is a transient user-facing delta: it never mutates the tree.
    expect(h.controller.replica.getState()?.agents.scout).toBeUndefined()
  })

  it("stops fanning out deltas after unsubscribe", () => {
    const h = harness()
    const seen: Delta[] = []
    const off = h.controller.subscribeDeltas((delta) => seen.push(delta))
    off()
    const socket = h.sockets[0]
    socket?.onopen?.()
    socket?.onmessage?.(
      JSON.stringify({
        type: "user_notification",
        agent: "scout",
        kind: "message",
        title: "scout",
        body: "hi",
      }),
    )
    expect(seen).toEqual([])
  })

  it("closes the socket and reports the closed state", () => {
    const h = harness()
    h.sockets[0]?.onopen?.()
    h.controller.close()
    expect(h.sockets[0]?.closed).toBe(true)
    expect(h.controller.getSyncState()).toBe("closed")
  })
})
