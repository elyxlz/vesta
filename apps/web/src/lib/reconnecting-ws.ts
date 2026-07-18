const DEFAULT_BASE_DELAY_MS = 1000;
const DEFAULT_MAX_DELAY_MS = 30000;

export interface ReconnectingWsHandle {
  /** The live socket, or null while down/reconnecting. */
  current: () => WebSocket | null;
  /** Stop the loop and tear down the socket. Idempotent. */
  close: () => void;
}

export interface ReconnectingWsOptions {
  /**
   * Async work to run before each connect attempt (token refresh, version
   * fetch). `"open"` proceeds to the socket; `"stop"` ends the loop without
   * opening or reconnecting (e.g. an expired session or a version mismatch).
   */
  beforeConnect?: () => Promise<"open" | "stop">;
  /** Build the socket URL. Throwing schedules a retry (URL not ready yet). */
  url: () => string;
  onOpen?: () => void;
  /** Each text frame; binary frames are ignored. */
  onMessage: (data: string) => void;
  onClose?: () => void;
  baseDelayMs?: number;
  maxDelayMs?: number;
}

/**
 * A self-healing WebSocket: it (re)connects with exponential backoff, resets the
 * backoff on a successful open, and reconnects on close. The single owner of the
 * connect/backoff/teardown shape shared by the chat, notification-tap, and gateway
 * sockets. `close()` cancels the loop and detaches `onclose` so teardown never
 * triggers a reconnect.
 */
export function connectReconnectingWs(
  options: ReconnectingWsOptions,
): ReconnectingWsHandle {
  const baseDelay = options.baseDelayMs ?? DEFAULT_BASE_DELAY_MS;
  const maxDelay = options.maxDelayMs ?? DEFAULT_MAX_DELAY_MS;
  let cancelled = false;
  let socket: WebSocket | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let delay = baseDelay;

  const scheduleReconnect = () => {
    timer = setTimeout(() => void connect(), delay);
    delay = Math.min(delay * 2, maxDelay);
  };

  // connect only runs while the loop is live (the initial call, and timers that
  // close() clears), so the sole cancellation window is the beforeConnect await.
  async function connect() {
    if (options.beforeConnect) {
      const verdict = await options.beforeConnect();
      if (cancelled) return;
      if (verdict === "stop") {
        cancelled = true;
        return;
      }
    }
    let url: string;
    try {
      url = options.url();
    } catch {
      scheduleReconnect();
      return;
    }
    const sock = new WebSocket(url);
    socket = sock;
    sock.onopen = () => {
      if (cancelled) return;
      delay = baseDelay;
      options.onOpen?.();
    };
    sock.onmessage = (event) => {
      if (cancelled || typeof event.data !== "string") return;
      options.onMessage(event.data);
    };
    sock.onclose = () => {
      socket = null;
      if (cancelled) return;
      options.onClose?.();
      scheduleReconnect();
    };
    sock.onerror = () => {
      /* noop: the paired close event owns the reconnect */
    };
  }

  void connect();

  return {
    current: () => socket,
    close: () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      if (socket) {
        socket.onclose = null;
        socket.close();
        socket = null;
      }
    },
  };
}
