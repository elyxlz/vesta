import { readSse, type SseHandle } from "@vesta/core";
import type { LogEvent } from "@/lib/types";
import { httpClient } from "./client";

// The one owner of the SSE log protocol shared by per-agent logs and the gateway stream, over core's
// readSse (the same fetch-based reader mobile drives). Reading through the app's http client is what
// authenticates the stream: it stamps `Authorization: Bearer`, pre-flights an expiring token, and
// retries once on a 401, so a viewer left open for hours never dials a stale token. readSse already
// maps "error:"-prefixed payloads to error and the caller's stopped event to end; this only adapts
// core's lowercase StreamEvent to the viewer's LogEvent. `onClose` fires on a clean end so the caller
// drops its handle; a transport error surfaces as an Error the viewer's policy reconnects on.
export function openLogStream(
  path: string,
  stoppedEvent: string,
  onEvent: (event: LogEvent) => void,
  onClose: () => void,
): SseHandle {
  return readSse(
    { fetch: httpClient.request, url: path, stoppedEvent },
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
