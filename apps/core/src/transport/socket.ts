import { encodeFrame, reauthFrame, unwatchFrame, watchFrame } from "../protocol/frames"
import { parseServerFrame } from "../protocol/parse"
import { PROTOCOL_FLOOR, PROTOCOL_VERSION } from "../protocol/version"
import { createWatchManager } from "../replica/watch"
import type { ClientFrame, HelloFrame } from "../protocol/frames"
import type { Delta } from "../protocol/deltas"
import type { Tree } from "../protocol/tree"

export type SyncState = "connecting" | "open" | "reconnecting" | "incompatible" | "closed"

export interface SocketLike {
  send: (data: string) => void
  close: () => void
  onopen: (() => void) | null
  onmessage: ((data: string) => void) | null
  onclose: (() => void) | null
}

export interface SyncSocketDeps {
  buildUrl: () => string
  createSocket: (url: string) => SocketLike
  setTimer: (fn: () => void, ms: number) => number
  clearTimer: (handle: number) => void
  baseDelayMs?: number
  maxDelayMs?: number
}

export interface SyncSocketCallbacks {
  onSnapshot: (tree: Tree) => void
  onDelta: (delta: Delta) => void
  onStateChange: (state: SyncState) => void
}

export interface SyncSocket {
  watch: (agent: string) => void
  unwatch: (agent: string) => void
  reauth: (token: string) => void
  close: () => void
}

// Compatible when the client's supported protocol range overlaps the server's:
// the client is not below the server's floor and the server is not below the
// client's floor. Otherwise the socket is terminally incompatible.
function compatible(hello: HelloFrame): boolean {
  return hello.floor <= PROTOCOL_VERSION && PROTOCOL_FLOOR <= hello.protocol
}

export function createSyncSocket(deps: SyncSocketDeps, callbacks: SyncSocketCallbacks): SyncSocket {
  const base = deps.baseDelayMs ?? 1000
  const max = deps.maxDelayMs ?? 30000
  const watches = createWatchManager()
  let socket: SocketLike | null = null
  let timer: number | null = null
  let delay = base
  let terminal = false

  const detach = (target: SocketLike): void => {
    target.onopen = null
    target.onmessage = null
    target.onclose = null
  }

  const emit = (frame: ClientFrame): void => {
    if (socket) socket.send(encodeFrame(frame))
  }

  const scheduleReconnect = (): void => {
    callbacks.onStateChange("reconnecting")
    timer = deps.setTimer(() => {
      connect()
    }, delay)
    delay = Math.min(delay * 2, max)
  }

  const goIncompatible = (): void => {
    terminal = true
    if (socket) {
      detach(socket)
      socket.close()
      socket = null
    }
    callbacks.onStateChange("incompatible")
  }

  const handleMessage = (data: string): void => {
    const parsed = parseServerFrame(data)
    switch (parsed.kind) {
      case "hello":
        if (!compatible(parsed.frame)) goIncompatible()
        return
      case "snapshot":
        callbacks.onSnapshot(parsed.frame.tree)
        return
      case "delta":
        if (parsed.delta.type === "agent_removed") watches.unwatch(parsed.delta.name)
        callbacks.onDelta(parsed.delta)
        return
      case "unknown":
        return
    }
  }

  function connect(): void {
    if (terminal) return
    callbacks.onStateChange("connecting")
    let url: string
    try {
      url = deps.buildUrl()
    } catch {
      scheduleReconnect()
      return
    }
    const current = deps.createSocket(url)
    socket = current
    current.onopen = () => {
      if (socket !== current) return
      delay = base
      callbacks.onStateChange("open")
      for (const agent of watches.desired()) current.send(encodeFrame(watchFrame(agent)))
    }
    current.onmessage = (data) => {
      if (socket === current) handleMessage(data)
    }
    current.onclose = () => {
      if (socket !== current) return
      socket = null
      if (terminal) return
      scheduleReconnect()
    }
  }

  connect()

  return {
    watch: (agent) => {
      watches.watch(agent)
      emit(watchFrame(agent))
    },
    unwatch: (agent) => {
      watches.unwatch(agent)
      emit(unwatchFrame(agent))
    },
    reauth: (token) => {
      emit(reauthFrame(token))
    },
    close: () => {
      terminal = true
      if (timer !== null) {
        deps.clearTimer(timer)
        timer = null
      }
      if (socket) {
        detach(socket)
        socket.close()
        socket = null
      }
      callbacks.onStateChange("closed")
    },
  }
}
