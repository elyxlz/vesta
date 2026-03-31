import { writable, type Writable, type Readable } from "svelte/store";
import type { VestaEvent, BoxActivityState } from "./types";
import { invoke, Channel } from "@tauri-apps/api/core";

const RECONNECT_BASE = 1000;
const RECONNECT_MAX = 30000;
const MAX_MESSAGES = 5000;

interface WsEvent {
  kind: "Message" | "Open" | "Close" | "Error";
  text?: string;
  message?: string;
}

export interface BoxConnection {
  messages: Readable<VestaEvent[]>;
  boxState: Readable<BoxActivityState>;
  connected: Readable<boolean>;
  connect(): void;
  disconnect(): void;
  send(text: string): boolean;
  resetReconnect(): void;
}

export function createBoxConnection(name: string): BoxConnection {
  const _messages: Writable<VestaEvent[]> = writable([]);
  const _boxState: Writable<BoxActivityState> = writable("idle");
  const _connected: Writable<boolean> = writable(false);

  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectDelay = RECONNECT_BASE;
  let active = false;
  let isConnected = false;

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

  async function doConnect() {
    if (isConnected) return;

    const channel = new Channel<WsEvent>();
    channel.onmessage = (event) => {
      switch (event.kind) {
        case "Open":
          isConnected = true;
          reconnectDelay = RECONNECT_BASE;
          _connected.set(true);
          _messages.set([]);
          break;
        case "Message":
          if (event.text) {
            try {
              handleEvent(JSON.parse(event.text) as VestaEvent);
            } catch (e) {
              console.warn("ws: bad message", e);
            }
          }
          break;
        case "Close":
          isConnected = false;
          _connected.set(false);
          if (active) {
            reconnectTimer = setTimeout(doConnect, reconnectDelay);
            reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX);
          }
          break;
        case "Error":
          console.warn("ws error:", event.message);
          break;
      }
    };

    try {
      await invoke("connect_ws", { name, onEvent: channel });
    } catch (e) {
      console.warn("ws: connect failed", e);
      if (active) {
        reconnectTimer = setTimeout(doConnect, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX);
      }
    }
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
    isConnected = false;
    _connected.set(false);
    invoke("disconnect_ws", { name }).catch(() => {});
  }

  function resetReconnect() {
    reconnectDelay = RECONNECT_BASE;
    if (active && !isConnected) {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      doConnect();
    }
  }

  function send(text: string): boolean {
    if (!isConnected) return false;
    invoke("send_ws", { name, text: JSON.stringify({ type: "message", text }) }).catch(() => {});
    return true;
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
