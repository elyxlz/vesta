import type { ChatMessage } from "./chat-stream-model"
import type { SocketLike } from "../transport/socket"

export type ChatSocketState = "connecting" | "open" | "reconnecting" | "closed"

export interface ChatSocketDeps {
  // Async and re-asked on every attempt, so the credential in the URL is the one live at connect
  // rather than one captured at mount: the builder mints or refreshes as needed, and a socket that
  // reconnects hours later never dials with something that expired while the client was away.
  buildUrl: () => Promise<string>
  createSocket: (url: string) => SocketLike
  setTimer: (fn: () => void, ms: number) => number
  clearTimer: (handle: number) => void
  baseDelayMs?: number
  maxDelayMs?: number
}

export interface ChatSocketCallbacks {
  onEvent: (event: ChatMessage) => void
  // Fires on every transition; the hook reseeds the tail by id whenever it sees "open" (initial
  // connect and every reconnect), which reconciles any gap the replay-free socket skipped.
  onStateChange: (state: ChatSocketState) => void
  // The FIRST close-without-open of a streak: the gateway refused the handshake, which is what a
  // revoked or expired credential looks like from here (a WebSocket exposes no status). The call
  // site drops the credential the URL carried, so the next attempt's buildUrl replaces it instead
  // of backing off forever against one the gateway will keep refusing. Fires at most once until
  // the next successful open, because a second consecutive failure cannot be the fresh
  // credential's fault: it is a refusal of the socket's own (an agent that is simply down), and
  // re-reporting it would mint a key per backoff tick for as long as that lasted.
  onClosedBeforeOpen: () => void
}

export interface ChatSocket {
  close: () => void
}

// A dumb, replay-free socket over SocketLike + the same backoff idiom as createSyncSocket, minus
// hello/snapshot/watch. Each inbound text frame is one ChatMessage; the store holds the durable copy,
// so a reconnect self-heals by the hook refetching the tail on "open".
export function createChatSocket(deps: ChatSocketDeps, callbacks: ChatSocketCallbacks): ChatSocket {
  const base = deps.baseDelayMs ?? 1000
  const max = deps.maxDelayMs ?? 30000
  let socket: SocketLike | null = null
  let timer: number | null = null
  let delay = base
  let terminal = false
  // Whether the next close-without-open still counts as a refusal worth reporting. Spent on the
  // first one of a streak and re-armed by every successful open, which is what bounds the reports
  // to one per streak.
  let refusalArmed = true
  // True once close() has retired this socket for good. Read through a call because a connect in
  // flight has to re-ask after awaiting its URL.
  const retired = (): boolean => terminal

  const detach = (target: SocketLike): void => {
    target.onopen = null
    target.onmessage = null
    target.onclose = null
  }

  const scheduleReconnect = (): void => {
    callbacks.onStateChange("reconnecting")
    timer = deps.setTimer(() => {
      void connect()
    }, delay)
    delay = Math.min(delay * 2, max)
  }

  const handleMessage = (data: string): void => {
    let event: ChatMessage
    try {
      event = JSON.parse(data) as ChatMessage
    } catch {
      return
    }
    callbacks.onEvent(event)
  }

  async function connect(): Promise<void> {
    if (retired()) return
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
    let opened = false
    current.onopen = () => {
      if (socket !== current) return
      opened = true
      refusalArmed = true
      delay = base
      callbacks.onStateChange("open")
    }
    current.onmessage = (data) => {
      if (socket === current) handleMessage(data)
    }
    current.onclose = () => {
      if (socket !== current) return
      socket = null
      if (!opened && refusalArmed) {
        refusalArmed = false
        callbacks.onClosedBeforeOpen()
      }
      if (!terminal) scheduleReconnect()
    }
  }

  void connect()

  return {
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
