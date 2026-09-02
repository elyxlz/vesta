import { ApiError } from "./http";
import type { FetchLike } from "./http";

export type StreamEvent =
  | { kind: "line"; text: string }
  | { kind: "end" }
  | { kind: "error"; message: string };

// One SSE block parsed to its event name and joined data payload; `:` comment lines
// (keep-alives) are ignored. Shared by the streaming reader and the one-shot pipeline drain.
function parseSseBlock(block: string): { name: string; data: string } {
  let name = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    else if (line.startsWith("event:")) name = line.slice(6).trim();
  }
  return { name, data: data.join("\n") };
}

export interface SseDeps {
  // The caller's authenticated fetch (each app's http client), so credentials, token
  // refresh, and the gateway base are its business and never this reader's: `url` is
  // whatever that fetch resolves, a gateway-relative path for the log routes.
  fetch: FetchLike;
  url: string;
  stoppedEvent: string;
}

export interface SseHandle {
  cancel: () => void;
}

export function readSse(
  deps: SseDeps,
  onEvent: (event: StreamEvent) => void,
): SseHandle {
  let cancelled = false;
  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  const isCancelled = (): boolean => cancelled;

  const fail = (message: string): void => {
    if (cancelled) return;
    cancelled = true;
    onEvent({ kind: "error", message });
  };

  // Honor the caller's stopped event as end, and map an "error:"-prefixed payload
  // to an error event.
  const dispatch = (block: string): boolean => {
    const { name, data: text } = parseSseBlock(block);
    if (name === deps.stoppedEvent) {
      cancelled = true;
      onEvent({ kind: "end" });
      return true;
    }
    onEvent(
      text.startsWith("error:")
        ? { kind: "error", message: text }
        : { kind: "line", text },
    );
    return false;
  };

  const pump = async (): Promise<void> => {
    let response: Response;
    try {
      response = await deps.fetch(deps.url);
    } catch {
      fail("log stream disconnected");
      return;
    }
    if (isCancelled()) return;
    if (!response.ok || !response.body) {
      fail("log stream disconnected");
      return;
    }
    reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      for (;;) {
        const chunk = await reader.read();
        if (isCancelled()) return;
        if (chunk.done) {
          onEvent({ kind: "end" });
          return;
        }
        buffer += decoder.decode(chunk.value, { stream: true });
        let index = buffer.indexOf("\n\n");
        while (index !== -1) {
          const block = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          if (dispatch(block)) return;
          index = buffer.indexOf("\n\n");
        }
      }
    } catch {
      fail("log stream disconnected");
    }
  };

  void pump();

  return {
    cancel: () => {
      cancelled = true;
      if (reader) void reader.cancel();
    },
  };
}

// A backup/restore pipeline endpoint (vestad's spawn_pipeline_sse) streams keep-alives, then
// closes with one terminal event: `done` carrying the result payload, or `error` carrying
// `{status, error}`. The whole body arrives at close, so read it in one shot: resolve the
// `done` payload, reject an `error` as an ApiError, reject a stream that closed with neither.
export async function drainSsePipeline(response: Response): Promise<string> {
  const raw = await response.text();
  for (const block of raw.split("\n\n")) {
    const { name, data } = parseSseBlock(block);
    if (name === "error") throw pipelineError(data, response.status);
    if (name === "done") return data;
  }
  throw new ApiError(response.status, "pipeline ended without a result");
}

function pipelineError(payload: string, fallbackStatus: number): ApiError {
  try {
    const parsed: unknown = JSON.parse(payload);
    if (parsed !== null && typeof parsed === "object") {
      const record = parsed as Record<string, unknown>;
      const message = typeof record.error === "string" ? record.error : payload;
      const status =
        typeof record.status === "number" ? record.status : fallbackStatus;
      return new ApiError(status, message);
    }
  } catch {
    return new ApiError(fallbackStatus, payload);
  }
  return new ApiError(fallbackStatus, payload);
}
