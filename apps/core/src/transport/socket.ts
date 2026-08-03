import { clientContextFrame, encodeFrame, reauthFrame } from "../protocol/frames"
import { parseServerFrame } from "../protocol/parse"
import { clientAheadOfGateway, clientBelowMinimum } from "../protocol/release-version"
import type { ClientFrame, ClientKind, HelloFrame } from "../protocol/frames"
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
  // Async so the builder can refresh an expiring token before each attempt: the URL carries the
  // access token, so a client waking from sleep would otherwise burn its whole backoff presenting
  // one that expired while it was away. Throwing means "no connectable URL", which backs off.
  buildUrl: () => Promise<string>
  createSocket: (url: string) => SocketLike
  setTimer: (fn: () => void, ms: number) => number
  clearTimer: (handle: number) => void
  // This client's own release version, used to block running ahead of the gateway. Omitted (or
  // unparseable) fails open, so a dev build with a non-semver version never blocks.
  clientVersion?: string
  clientKind: ClientKind
  // This device's stable installation id and self-composed label, reported so vestad tracks it in
  // the device registry. Omitted by a build that has no identity to report; then it is untracked.
  device?: { id: string; descriptor: string }
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
  reportPresence: (focused: boolean) => void
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
  let lastFocused: boolean | null = null
  // Whether the gateway already has `lastFocused`. False while a report is still undelivered, so
  // its replay goes out as the fresh focus it is rather than as a resync.
  let focusSynced = false
  // A token whose reauth was issued before the socket opened, held for that open. The gateway arms
  // the session deadline from the connect token and only a reauth extends it, so dropping the frame
  // would strand a live socket on a token that is about to expire.
  let pendingToken: string | null = null
  // True once close() or the app_behind gate has retired this socket for good. Read through a
  // call because a connect in flight has to re-ask after awaiting its URL.
  const retired = (): boolean => terminal

  const detach = (target: SocketLike): void => {
    target.onopen = null
    target.onmessage = null
    target.onclose = null
  }

  // A browser WebSocket throws before OPEN, so the connecting window never sends. Reports whether
  // the frame reached the gateway; both client frames are last-write-wins, so an undelivered one is
  // re-issued from its cached value on open.
  const emit = (frame: ClientFrame): boolean => {
    if (!open || !socket) return false
    socket.send(encodeFrame(frame))
    return true
  }

  const scheduleReconnect = (): void => {
    callbacks.onStateChange("reconnecting")
    timer = deps.setTimer(() => {
      void connect()
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

  async function connect(): Promise<void> {
    if (retired()) return
    open = false
    callbacks.onStateChange("connecting")
    let url: string
    try {
      url = await deps.buildUrl()
    } catch {
      scheduleReconnect()
      return
    }
    // close() can land while the builder is refreshing a token.
    if (retired()) return
    const current = deps.createSocket(url)
    socket = current
    current.onopen = () => {
      if (socket !== current) return
      open = true
      delay = base
      if (pendingToken !== null) {
        current.send(encodeFrame(reauthFrame(pendingToken)))
        pendingToken = null
      }
      // Replay cached presence. Already delivered means this is a reconnect, so it goes out as a
      // resync and vestad doesn't read it as the user returning; never delivered (the report was
      // issued while the socket was still connecting) means this is that first genuine focus.
      if (lastFocused !== null) {
        current.send(encodeFrame(clientContextFrame(lastFocused, deps.clientKind, focusSynced, deps.device)))
        focusSynced = true
      }
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

  void connect()

  return {
    reauth: (token) => {
      if (!emit(reauthFrame(token))) pendingToken = token
    },
    reportPresence: (focused) => {
      // Skip repeated AppState/window-focus reports; the cached value still drives reconnect replay.
      if (lastFocused === focused) return
      lastFocused = focused
      // A genuine user-driven report (resync=false): vestad may fire the return-to-focus notification.
      focusSynced = emit(clientContextFrame(focused, deps.clientKind, false, deps.device))
    },
    close: () => {
      terminal = true
      open = false
      pendingToken = null
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
