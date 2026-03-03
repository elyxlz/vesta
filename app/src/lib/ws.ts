import { writable, type Readable } from "svelte/store";
import type { VestaEvent, AgentActivityState } from "./types";
import { agentHost } from "./api";

const DEFAULT_WS_PORT = 7865;
const RECONNECT_BASE = 1000;
const RECONNECT_MAX = 30000;
const MAX_MESSAGES = 5000;

let agentPort = DEFAULT_WS_PORT;
let wsUrl = `ws://localhost:${agentPort}/ws`;
let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectDelay = RECONNECT_BASE;
let refCount = 0;

const _messages = writable<VestaEvent[]>([]);
const _agentState = writable<AgentActivityState>("idle");
const _connected = writable(false);

export const messages: Readable<VestaEvent[]> = _messages;
export const agentState: Readable<AgentActivityState> = _agentState;
export const connected: Readable<boolean> = _connected;

function handleEvent(event: VestaEvent) {
  if (event.type === "history") {
    const evts = event.events;
    _messages.set(evts.length > MAX_MESSAGES ? evts.slice(-MAX_MESSAGES) : evts);
    if (event.state) _agentState.set(event.state);
    return;
  }
  _messages.update((msgs) => {
    msgs.push(event);
    if (msgs.length > MAX_MESSAGES) msgs.splice(0, msgs.length - MAX_MESSAGES);
    return msgs;
  });
  if (event.type === "status") {
    _agentState.set(event.state);
  }
}

function killSocket(socket: WebSocket) {
  socket.onopen = null;
  socket.onmessage = null;
  socket.onclose = null;
  socket.onerror = null;
  socket.close();
}

async function doConnect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  try {
    const host = await agentHost();
    wsUrl = `ws://${host}:${agentPort}/ws`;
  } catch {}

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
    if (refCount > 0) {
      reconnectTimer = setTimeout(doConnect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX);
    }
  };

  socket.onerror = () => {
    socket.close();
  };
}

export function connect() {
  refCount++;
  if (refCount === 1) {
    _messages.set([]);
    doConnect();
  }
}

export function disconnect() {
  refCount = Math.max(0, refCount - 1);
  if (refCount === 0) {
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
}

export function resetReconnect() {
  reconnectDelay = RECONNECT_BASE;
  if (refCount > 0 && !ws) {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    doConnect();
  }
}

export function setPort(port: number) {
  agentPort = port;
}

export function send(text: string): boolean {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "message", text }));
    return true;
  }
  return false;
}
