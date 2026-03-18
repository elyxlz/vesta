import { writable, type Writable, type Readable } from "svelte/store";
import type { VestaEvent, BoxActivityState } from "./types";
import { boxHost } from "./api";

const RECONNECT_BASE = 1000;
const RECONNECT_MAX = 30000;
const MAX_MESSAGES = 5000;

export interface BoxConnection {
  messages: Readable<VestaEvent[]>;
  boxState: Readable<BoxActivityState>;
  connected: Readable<boolean>;
  connect(): void;
  disconnect(): void;
  send(text: string): boolean;
  resetReconnect(): void;
}

export function createBoxConnection(port: number): BoxConnection {
  const _messages: Writable<VestaEvent[]> = writable([]);
  const _boxState: Writable<BoxActivityState> = writable("idle");
  const _connected: Writable<boolean> = writable(false);

  let ws: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectDelay = RECONNECT_BASE;
  let active = false;

  function handleEvent(event: VestaEvent) {
    if (event.type === "history") {
      const evts = event.events;
      _messages.set(evts.length > MAX_MESSAGES ? evts.slice(-MAX_MESSAGES) : evts);
      if (event.state) _boxState.set(event.state);
      return;
    }
    _messages.update((msgs) => {
      const updated = [...msgs, event];
      if (updated.length > MAX_MESSAGES) updated.splice(0, updated.length - MAX_MESSAGES);
      return updated;
    });
    if (event.type === "status") {
      _boxState.set(event.state);
    }
  }

  function killSocket(socket: WebSocket) {
    socket.onopen = null;
    socket.onmessage = null;
    socket.onclose = null;
    socket.onerror = null;
    socket.close();
  }

  let cachedHost: string | null = null;

  async function doConnect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    if (!cachedHost) {
      try {
        cachedHost = await boxHost();
      } catch {
        cachedHost = "localhost";
      }
    }
    const wsUrl = `ws://${cachedHost}:${port}/ws`;

    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const socket = new WebSocket(wsUrl);
    ws = socket;

    socket.onopen = () => {
      reconnectDelay = RECONNECT_BASE;
      _connected.set(true);
      _messages.set([]);
    };

    socket.onmessage = (ev) => {
      try {
        handleEvent(JSON.parse(ev.data) as VestaEvent);
      } catch (e) {
        console.warn("ws: bad message", e);
      }
    };

    socket.onclose = () => {
      if (ws !== socket) return;
      _connected.set(false);
      ws = null;
      if (active) {
        reconnectTimer = setTimeout(doConnect, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX);
      }
    };

    socket.onerror = () => {
      socket.close();
    };
  }

  function connect() {
    if (active) return;
    active = true;
    _messages.set([]);
    doConnect();
  }

  function disconnect() {
    active = false;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (ws) {
      killSocket(ws);
      ws = null;
    }
    _connected.set(false);
  }

  function resetReconnect() {
    reconnectDelay = RECONNECT_BASE;
    if (active && !ws) {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      doConnect();
    }
  }

  function send(text: string): boolean {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "message", text }));
      return true;
    }
    return false;
  }

  return {
    messages: _messages,
    boxState: _boxState,
    connected: _connected,
    connect,
    disconnect,
    send,
    resetReconnect,
  };
}
