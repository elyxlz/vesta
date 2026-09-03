import { adaptWebSocket, type SocketLike } from "./websocket";

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

export type ReconnectPhase = "connecting" | "open" | "reconnecting" | "closed";

export interface ReconnectingSocketDeps {
  // Async and re-asked on every attempt, so the credential in the URL is the one live at connect
  // rather than one captured at mount: the builder refreshes the access token as needed, and a
  // socket that reconnects hours later never dials with one that expired while the client was away.
  // Throwing means "no connectable URL", which backs off like a failed dial.
  buildUrl: () => Promise<string>;
  // Defaults to the platform WebSocket; tests inject a fake.
  createSocket?: (url: string) => SocketLike;
  baseDelayMs?: number;
  maxDelayMs?: number;
}

export interface ReconnectingSocketCallbacks {
  // Fires once per open with the live socket, before the "open" phase is reported, so a consumer
  // can replay cached frames onto the fresh connection ahead of anything else.
  onOpen: (socket: SocketLike) => void;
  onMessage: (data: string) => void;
  onPhaseChange: (phase: ReconnectPhase) => void;
}

export interface ReconnectingSocket {
  // Sends while open; reports whether the frame reached the socket, since a browser WebSocket
  // throws before OPEN and the connecting window never sends.
  send: (data: string) => boolean;
  // Retires the socket for good: no reconnect, no further callbacks except the final phase.
  close: () => void;
}

// One socket lifetime is a small state machine: dialing (awaiting the URL), connecting (a socket
// exists but has not opened), open, reconnecting (a backoff timer is pending), closed (terminal).
// A stale socket's events are ignored by identity, so a close that lands after a reconnect never
// tears down its successor.
type Phase =
  | { kind: "dialing" }
  | { kind: "connecting"; socket: SocketLike }
  | { kind: "open"; socket: SocketLike }
  | { kind: "reconnecting"; timer: ReturnType<typeof setTimeout> }
  | { kind: "closed" };

export function createReconnectingSocket(
  deps: ReconnectingSocketDeps,
  callbacks: ReconnectingSocketCallbacks,
): ReconnectingSocket {
  const base = deps.baseDelayMs ?? RECONNECT_BASE_MS;
  const max = deps.maxDelayMs ?? RECONNECT_MAX_MS;
  let phase: Phase = { kind: "dialing" };
  // Read through a call after an await, since close() can land while the URL is being built.
  const phaseNow = (): Phase => phase;
  let delay = base;

  const detach = (target: SocketLike): void => {
    target.onopen = null;
    target.onmessage = null;
    target.onclose = null;
  };

  const scheduleReconnect = (): void => {
    if (phase.kind === "reconnecting") clearTimeout(phase.timer);
    phase = {
      kind: "reconnecting",
      timer: setTimeout(() => {
        void connect();
      }, delay),
    };
    delay = Math.min(delay * 2, max);
    callbacks.onPhaseChange("reconnecting");
  };

  async function connect(): Promise<void> {
    if (phase.kind === "closed") return;
    phase = { kind: "dialing" };
    callbacks.onPhaseChange("connecting");
    let url: string;
    try {
      url = await deps.buildUrl();
    } catch {
      if (phaseNow().kind !== "closed") scheduleReconnect();
      return;
    }
    if (phaseNow().kind !== "dialing") return;
    const current = (deps.createSocket ?? adaptWebSocket)(url);
    phase = { kind: "connecting", socket: current };
    current.onopen = () => {
      if (phase.kind !== "connecting" || phase.socket !== current) return;
      phase = { kind: "open", socket: current };
      delay = base;
      callbacks.onOpen(current);
      callbacks.onPhaseChange("open");
    };
    current.onmessage = (data) => {
      if (
        (phase.kind === "open" || phase.kind === "connecting") &&
        phase.socket === current
      )
        callbacks.onMessage(data);
    };
    current.onclose = () => {
      if (
        (phase.kind === "open" || phase.kind === "connecting") &&
        phase.socket === current
      )
        scheduleReconnect();
    };
  }

  void connect();

  return {
    send: (data) => {
      if (phase.kind !== "open") return false;
      phase.socket.send(data);
      return true;
    },
    close: () => {
      const previous = phase;
      phase = { kind: "closed" };
      if (previous.kind === "reconnecting") clearTimeout(previous.timer);
      if (previous.kind === "open" || previous.kind === "connecting") {
        detach(previous.socket);
        previous.socket.close();
      }
      callbacks.onPhaseChange("closed");
    },
  };
}
