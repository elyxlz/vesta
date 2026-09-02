import {
  agentLogsPath,
  readSse,
  type SseHandle,
  type StreamEvent,
} from "@vesta/core";
import type { ApiClient } from "@/api/client";

// The agent log SSE read. The api client's own request is the fetch, so the stream presents
// `Authorization: Bearer`, pre-flights an expiring token, and retries once on a 401 exactly like
// every other gateway read, and no credential ever reaches the URL. A reconnect asks for no tail,
// since the replayed block is already on screen and would re-append as duplicates.
export function openAgentLogStream(
  api: ApiClient,
  name: string,
  reconnect: boolean,
  onEvent: (event: StreamEvent) => void,
): SseHandle {
  return readSse(
    {
      fetch: api.request,
      url: agentLogsPath(name, reconnect ? 0 : undefined),
      stoppedEvent: "agent_stopped",
    },
    onEvent,
  );
}
