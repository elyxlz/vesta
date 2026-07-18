import type { ApiClient } from "./client";

export type LogEvent =
  | { kind: "Line"; text: string }
  | { kind: "End" }
  | { kind: "Error"; message: string };

interface SseMessage {
  event: string;
  data: string;
}

export function parseSseBlock(block: string): SseMessage | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return data.length > 0 || event !== "message"
    ? { event, data: data.join("\n") }
    : null;
}

export async function streamLogs(
  api: ApiClient,
  path: string,
  stoppedEvent: "agent_stopped" | "gateway_stopped",
  signal: AbortSignal,
  onEvent: (event: LogEvent) => void,
): Promise<void> {
  try {
    const response = await api.request(path, {
      headers: { Accept: "text/event-stream" },
      signal,
    });
    const reader = response.body?.getReader();
    if (!reader) throw new Error("This device cannot stream logs.");
    const decoder = new TextDecoder();
    let pending = "";

    while (!signal.aborted) {
      const result = await reader.read();
      if (result.done) break;
      pending += decoder.decode(result.value, { stream: true }).replace(/\r\n/g, "\n");
      let boundary = pending.indexOf("\n\n");
      while (boundary !== -1) {
        const message = parseSseBlock(pending.slice(0, boundary));
        pending = pending.slice(boundary + 2);
        boundary = pending.indexOf("\n\n");
        if (!message) continue;
        if (message.event === stoppedEvent) {
          onEvent({ kind: "End" });
          return;
        }
        onEvent(
          message.data.startsWith("error:")
            ? { kind: "Error", message: message.data }
            : { kind: "Line", text: message.data },
        );
      }
    }
  } catch (error) {
    if (signal.aborted) return;
    onEvent({
      kind: "Error",
      message: error instanceof Error ? error.message : "Log stream disconnected.",
    });
  }
}
