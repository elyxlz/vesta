import type { ChatMessage } from "./chat-stream-model"
import type { SocketLike } from "../transport/socket"

export type ChatSocketState = "connecting" | "open" | "reconnecting" | "closed"

export interface ChatSocketDeps {
  buildUrl: () => string
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

  const detach = (target: SocketLike): void => {
    target.onopen = null
    target.onmessage = null
    target.onclose = null
  }

  const scheduleReconnect = (): void => {
    callbacks.onStateChange("reconnecting")
    timer = deps.setTimer(() => {
      connect()
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
    }
    current.onmessage = (data) => {
      if (socket === current) handleMessage(data)
    }
    current.onclose = () => {
      if (socket !== current) return
      socket = null
      if (!terminal) scheduleReconnect()
    }
  }

  connect()

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
