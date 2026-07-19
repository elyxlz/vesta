import type { SocketLike } from "@vesta/core";

// Adapt the browser WebSocket to core's SocketLike. Only string frames reach core
// (the sync protocol is JSON text); binary messages are ignored. The error event is
// left to its paired close event, which owns reconnect.
export function createBrowserSocket(url: string): SocketLike {
  const ws = new WebSocket(url);
  const adapter: SocketLike = {
    send: (data) => ws.send(data),
    close: () => ws.close(),
    onopen: null,
    onmessage: null,
    onclose: null,
  };
  ws.onopen = () => adapter.onopen?.();
  ws.onmessage = (event) => {
    if (typeof event.data === "string") adapter.onmessage?.(event.data);
  };
  ws.onclose = () => adapter.onclose?.();
  ws.onerror = () => {
    // The paired close event owns reconnect; nothing to do here.
  };
  return adapter;
}
