import { encodeFrame, reauthFrame } from "../protocol/frames"
import { parseServerFrame } from "../protocol/parse"
import { clientAheadOfGateway, clientBelowMinimum } from "../protocol/release-version"
import type { ClientFrame, HelloFrame } from "../protocol/frames"
import type { Delta } from "../protocol/deltas"
import type { Tree } from "../protocol/tree"

// The hello's served window (min_supported <= client <= version) drives two blocked states.
// "app_behind" is terminal for the session: the client is older than the gateway's minimum, so
// only the app updating resolves it (no retry storm). "gateway_behind" is recoverable: the
// client is newer than the gateway, so the socket stays live and re-hellos into "open" once the
// gateway restarts newer.
export type SyncState =
  "connecting" | "open" | "reconnecting" | "app_behind" | "gateway_behind" | "closed"

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
  // This client's own release version, used to block running ahead of the gateway. Omitted (or
  // unparseable) fails open, so a dev build with a non-semver version never blocks.
  clientVersion?: string
  baseDelayMs?: number
  maxDelayMs?: number
}

export interface SyncSocketCallbacks {
  onSnapshot: (tree: Tree) => void
  onDelta: (delta: Delta) => void
  onStateChange: (state: SyncState) => void
}

export interface SyncSocket {
  reauth: (token: string) => void
  close: () => void
}

export function createSyncSocket(deps: SyncSocketDeps, callbacks: SyncSocketCallbacks): SyncSocket {
  const base = deps.baseDelayMs ?? 1000
  const max = deps.maxDelayMs ?? 30000
  let socket: SocketLike | null = null
  let timer: number | null = null
  let delay = base
  let terminal = false
  let open = false

  const detach = (target: SocketLike): void => {
    target.onopen = null
    target.onmessage = null
    target.onclose = null
  }

  // Only send on an open socket: a browser WebSocket throws before OPEN, so the connecting
  // window sends nothing (a reauth issued then is simply dropped; the next rotation resends).
  const emit = (frame: ClientFrame): void => {
    if (open && socket) socket.send(encodeFrame(frame))
  }

  const scheduleReconnect = (): void => {
    callbacks.onStateChange("reconnecting")
    timer = deps.setTimer(() => {
      connect()
    }, delay)
    delay = Math.min(delay * 2, max)
  }

  const goAppBehind = (): void => {
    terminal = true
    open = false
    if (socket) {
      detach(socket)
      socket.close()
      socket = null
    }
    callbacks.onStateChange("app_behind")
  }

  // Compare this client's own build version to the hello's served window. Fails open when the
  // client version is unknown (dev builds), and app_behind (terminal) wins over gateway_behind.
  const classifyHello = (hello: HelloFrame): SyncState | null => {
    const client = deps.clientVersion
    if (client === undefined) return null
    if (clientBelowMinimum(client, hello.minSupported)) return "app_behind"
    if (clientAheadOfGateway(client, hello.version)) return "gateway_behind"
    return null
  }

  const handleMessage = (data: string): void => {
    const parsed = parseServerFrame(data)
    switch (parsed.kind) {
      case "hello": {
        const outcome = classifyHello(parsed.frame)
        if (outcome === "app_behind") goAppBehind()
        else if (outcome === "gateway_behind") callbacks.onStateChange("gateway_behind")
        return
      }
      case "snapshot":
        callbacks.onSnapshot(parsed.frame.tree)
        return
      case "delta":
        callbacks.onDelta(parsed.delta)
        return
      case "unknown":
        return
    }
  }

  function connect(): void {
    if (terminal) return
    open = false
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
      open = true
      delay = base
      callbacks.onStateChange("open")
    }
    current.onmessage = (data) => {
      if (socket === current) handleMessage(data)
    }
    current.onclose = () => {
      if (socket !== current) return
      open = false
      socket = null
      if (terminal) return
      scheduleReconnect()
    }
  }

  connect()

  return {
    reauth: (token) => {
      emit(reauthFrame(token))
    },
    close: () => {
      terminal = true
      open = false
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
