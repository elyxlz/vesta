import type { LogEvent } from "@/lib/types";

// The one owner of the SSE log protocol shared by per-agent logs and the gateway stream:
// "error:"-prefixed lines become Error events, others Line; the "<x>_stopped" event or a
// transport error ends it. `onClose` lets the caller drop its handle and resolve its promise.
export function openLogStream(
  url: string,
  stoppedEvent: string,
  onEvent: (event: LogEvent) => void,
  onClose: () => void,
): EventSource {
  const es = new EventSource(url);

  es.onmessage = (e) => {
    const text = e.data;
    onEvent(
      text.startsWith("error:")
        ? { kind: "Error", message: text }
        : { kind: "Line", text },
    );
  };

  es.addEventListener(stoppedEvent, () => {
    onEvent({ kind: "End" });
    es.close();
    onClose();
  });

  es.onerror = () => {
    onEvent({ kind: "Error", message: "log stream disconnected" });
    es.close();
    onClose();
  };

  return es;
}
