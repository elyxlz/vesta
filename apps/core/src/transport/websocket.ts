// The one socket port every core transport dials through. Text frames carry the sync, chat,
// and voice protocols; the voice session additionally sends binary audio. The close reason is
// passed through for the consumers that read it (voice), and ignored by the ones that do not.
export interface SocketLike {
  send: (data: string | ArrayBuffer) => void;
  close: () => void;
  onopen: (() => void) | null;
  onmessage: ((data: string) => void) | null;
  onclose: ((reason: string) => void) | null;
}

// Adapt the platform WebSocket (browser and React Native share the global) to SocketLike. The
// consumer assigns the callbacks synchronously after this returns, before the platform can fire
// an event, so no open is lost. Only string frames reach the consumer; the error event is left to
// its paired close event, which owns reconnect. A send or close after the socket already closed
// is a no-op rather than a throw, since the consumer's own state is what decides retries.
export function adaptWebSocket(url: string): SocketLike {
  const ws = new WebSocket(url);
  ws.binaryType = "arraybuffer";
  const adapter: SocketLike = {
    send: (data) => {
      try {
        ws.send(data);
      } catch {
        // Closed between the consumer's check and this send.
      }
    },
    close: () => {
      try {
        ws.close();
      } catch {
        // Already closed.
      }
    },
    onopen: null,
    onmessage: null,
    onclose: null,
  };
  ws.onopen = () => adapter.onopen?.();
  ws.onmessage = (event: MessageEvent<unknown>) => {
    if (typeof event.data === "string") adapter.onmessage?.(event.data);
  };
  ws.onclose = (event) => adapter.onclose?.(event.reason);
  ws.onerror = () => {
    // The paired close event owns reconnect; nothing to do here.
  };
  return adapter;
}
