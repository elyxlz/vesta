import type { ChatMessage } from "./chat-stream-model";
import { adaptWebSocket, type SocketLike } from "../transport/websocket";

export type ChatSocketState = "connecting" | "open" | "reconnecting" | "closed";

export interface ChatSocketDeps {
  // Async and re-asked on every attempt, so the credential in the URL is the one live at connect
  // rather than one captured at mount: the builder refreshes the access token as needed, and a
  // socket that reconnects hours later never dials with one that expired while the client was away.
  buildUrl: () => Promise<string>;
  // Defaults to the platform WebSocket; tests inject a fake.
  createSocket?: (url: string) => SocketLike;
  setTimer: (fn: () => void, ms: number) => number;
  clearTimer: (handle: number) => void;
  baseDelayMs?: number;
  maxDelayMs?: number;
}

export interface ChatSocketCallbacks {
  onEvent: (event: ChatMessage) => void;
  // Fires on every transition; the hook reseeds the tail by id whenever it sees "open" (a
  // reconnect at least), which reconciles any gap the replay-free socket skipped.
  onStateChange: (state: ChatSocketState) => void;
}

export interface ChatSocket {
  // Reports whether the user is talking into a live voice conversation; the daemon holds the
  // agent's replies while it is true. The latest value is cached and a true is replayed on
  // reconnect open. With no open socket nothing is sent, which is the right answer: the daemon
  // ties the flag to the connection that set it and clears it when that connection drops.
  reportSpeaking: (speaking: boolean) => void;
  close: () => void;
}

// A dumb, replay-free socket over SocketLike + the same backoff idiom as createSyncSocket, minus
// hello/snapshot/watch. Each inbound text frame is one ChatMessage; the store holds the durable copy,
// so a reconnect self-heals by the hook refetching the tail on "open".
export function createChatSocket(
  deps: ChatSocketDeps,
  callbacks: ChatSocketCallbacks,
): ChatSocket {
  const base = deps.baseDelayMs ?? 1000;
  const max = deps.maxDelayMs ?? 30000;
  let socket: SocketLike | null = null;
  let open = false;
  let timer: number | null = null;
  let delay = base;
  let terminal = false;
  let speaking = false;

  const speakingFrame = (): string =>
    JSON.stringify({ type: "speaking", active: speaking });
  // True once close() has retired this socket for good. Read through a call because a connect in
  // flight has to re-ask after awaiting its URL.
  const retired = (): boolean => terminal;

  const detach = (target: SocketLike): void => {
    target.onopen = null;
    target.onmessage = null;
    target.onclose = null;
  };

  const scheduleReconnect = (): void => {
    callbacks.onStateChange("reconnecting");
    timer = deps.setTimer(() => {
      void connect();
    }, delay);
    delay = Math.min(delay * 2, max);
  };

  const handleMessage = (data: string): void => {
    let event: ChatMessage;
    try {
      event = JSON.parse(data) as ChatMessage;
    } catch {
      return;
    }
    callbacks.onEvent(event);
  };

  async function connect(): Promise<void> {
    if (retired()) return;
    callbacks.onStateChange("connecting");
    let url: string;
    try {
      url = await deps.buildUrl();
    } catch {
      scheduleReconnect();
      return;
    }
    // close() can land while the builder is refreshing a token.
    if (retired()) return;
    const current = (deps.createSocket ?? adaptWebSocket)(url);
    socket = current;
    current.onopen = () => {
      if (socket !== current) return;
      open = true;
      delay = base;
      callbacks.onStateChange("open");
      // A turn that outlived a reconnect is replayed, so the daemon's fresh connection holds it.
      if (speaking) current.send(speakingFrame());
    };
    current.onmessage = (data) => {
      if (socket === current) handleMessage(data);
    };
    current.onclose = () => {
      if (socket !== current) return;
      socket = null;
      open = false;
      if (!terminal) scheduleReconnect();
    };
  }

  void connect();

  return {
    reportSpeaking: (value) => {
      if (speaking === value) return;
      speaking = value;
      if (socket && open) socket.send(speakingFrame());
    },
    close: () => {
      terminal = true;
      if (timer !== null) {
        deps.clearTimer(timer);
        timer = null;
      }
      if (socket) {
        detach(socket);
        socket.close();
        socket = null;
      }
      callbacks.onStateChange("closed");
    },
  };
}
