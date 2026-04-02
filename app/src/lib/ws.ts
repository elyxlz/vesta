import { writable, type Writable, type Readable } from "svelte/store";
import type { VestaEvent, AgentActivityState } from "./types";
import { wsUrl } from "./connection";

const RECONNECT_BASE = 1000;
const RECONNECT_MAX = 30000;
const MAX_MESSAGES = 5000;

export interface AgentConnection {
  messages: Readable<VestaEvent[]>;
  agentState: Readable<AgentActivityState>;
  connected: Readable<boolean>;
  connect(): void;
  disconnect(): void;
  send(text: string): boolean;
  resetReconnect(): void;
}

export function createAgentConnection(name: string): AgentConnection {
  const _messages: Writable<VestaEvent[]> = writable([]);
  const _agentState: Writable<AgentActivityState> = writable("idle");
  const _connected: Writable<boolean> = writable(false);

  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectDelay = RECONNECT_BASE;
  let active = false;
  let ws: WebSocket | null = null;

  function handleEvent(event: VestaEvent) {
    if (event.type === "history") {
      const evts = event.events;
      _messages.set(evts.length > MAX_MESSAGES ? evts.slice(-MAX_MESSAGES) : evts);
      if (event.state) _agentState.set(event.state);
      return;
    }
    _messages.update((msgs) => {
      const updated = [...msgs, event];
      if (updated.length > MAX_MESSAGES) updated.splice(0, updated.length - MAX_MESSAGES);
      return updated;
    });
    if (event.type === "status") {
      _agentState.set(event.state);
    }
  }

  function doConnect() {
    if (ws) return;

    let url: string;
    try {
      url = wsUrl(name);
    } catch {
      if (active) {
        reconnectTimer = setTimeout(doConnect, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX);
      }
      return;
    }

    const socket = new WebSocket(url);
    ws = socket;

    socket.onopen = () => {
      reconnectDelay = RECONNECT_BASE;
      _connected.set(true);
      _messages.set([]);
    };

    socket.onmessage = (e) => {
      if (typeof e.data === "string") {
        try {
          handleEvent(JSON.parse(e.data) as VestaEvent);
        } catch (err) {
          console.warn("ws: bad message", err);
        }
      }
    };

    socket.onclose = () => {
      ws = null;
      _connected.set(false);
      if (active) {
        reconnectTimer = setTimeout(doConnect, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX);
      }
    };

    socket.onerror = (err) => {
      console.warn("ws error:", err);
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
      ws.close();
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
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ type: "message", text }));
    return true;
  }

  return {
    messages: _messages,
    agentState: _agentState,
    connected: _connected,
    connect,
    disconnect,
    send,
    resetReconnect,
  };
}
