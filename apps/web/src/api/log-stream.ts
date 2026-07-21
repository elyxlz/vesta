import { readSse, type SseHandle } from "@vesta/core";
import type { LogEvent } from "@/lib/types";

// The one owner of the SSE log protocol shared by per-agent logs and the gateway stream, over core's
// readSse (the same fetch-based reader mobile drives). readSse already maps "error:"-prefixed payloads
// to error and the caller's stopped event to end; this only adapts core's lowercase StreamEvent to the
// viewer's LogEvent. `onClose` fires on a clean end so the caller drops its handle and resolves its
// promise; a transport error surfaces as an Error the viewer's policy reconnects on (see Console).
export function openLogStream(
  url: string,
  stoppedEvent: string,
  onEvent: (event: LogEvent) => void,
  onClose: () => void,
): SseHandle {
  return readSse(
    { fetch: (input, init) => fetch(input, init), url, stoppedEvent },
    (event) => {
      switch (event.kind) {
        case "line":
          onEvent({ kind: "Line", text: event.text });
          break;
        case "error":
          onEvent({ kind: "Error", message: event.message });
          break;
        case "end":
          onEvent({ kind: "End" });
          onClose();
          break;
      }
    },
  );
}
