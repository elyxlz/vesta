import type { SseHandle, StreamEvent } from "@vesta/core";

export interface LogStream {
  open: (reconnect: boolean, onEvent: (event: StreamEvent) => void) => SseHandle;
  onLine: (text: string) => void;
  onError: (message: string) => void;
  retryDelayMs: number;
}

// Drive the agent log stream, retrying on error while keeping at most one live stream. An inline
// "error:" log line surfaces as a non-terminal error event (readSse leaves the socket open), so the
// live handle is cancelled before the retry opens the next one; without that a single error would
// leave two concurrent streams appending duplicate lines. Returns the teardown.
export function subscribeLogs(stream: LogStream): () => void {
  let cancelled = false;
  let handle: SseHandle | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let receivedLine = false;

  const open = (): void => {
    handle = stream.open(receivedLine, (event) => {
      if (cancelled) return;
      if (event.kind === "line") {
        receivedLine = true;
        stream.onLine(event.text);
      } else if (event.kind === "error") {
        stream.onError(event.message);
        handle?.cancel();
        handle = null;
        retryTimer = setTimeout(open, stream.retryDelayMs);
      }
    });
  };

  open();
  return () => {
    cancelled = true;
    handle?.cancel();
    if (retryTimer) clearTimeout(retryTimer);
  };
}
