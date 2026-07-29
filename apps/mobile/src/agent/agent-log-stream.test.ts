import { afterEach, describe, expect, it, vi } from "vitest";
import type { StreamEvent } from "@vesta/core";
import { createApiClient } from "@/api/client";
import type { ConnectionConfig } from "@/api/types";
import { openAgentLogStream } from "./agent-log-stream";

const connection: ConnectionConfig = {
  url: "https://gateway.example",
  accessToken: "access-token",
  refreshToken: "refresh-token",
  expiresAt: Date.now() + 60 * 60 * 1000,
  hosted: false,
};

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

function stubFetch(): ReturnType<typeof vi.fn<Fetch>> {
  const fetchMock = vi
    .fn<Fetch>()
    .mockResolvedValue(
      new Response("data: hello\n\nevent: agent_stopped\ndata: \n\n"),
    );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

// Read the whole stream through a real api client, then report the single request it sent.
async function streamAgentLogs(
  reconnect: boolean,
): Promise<{
  url: string;
  authorization: string | null;
  events: StreamEvent[];
}> {
  const fetchMock = stubFetch();
  const api = createApiClient({
    getConnection: () => connection,
    onConnectionChange: async () => undefined,
    onSessionExpired: async () => undefined,
  });
  const events: StreamEvent[] = [];

  openAgentLogStream(api, "ada", reconnect, (event) => events.push(event));
  await vi.waitFor(() => {
    expect(events.at(-1)?.kind).toBe("end");
  });

  const call = fetchMock.mock.calls[0];
  if (!call) throw new Error("expected the log stream to send a request");
  const [url, init] = call;
  return {
    url,
    authorization: new Headers(init?.headers).get("Authorization"),
    events,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("agent log stream", () => {
  it("presents the access token as a header, never in the URL", async () => {
    const sent = await streamAgentLogs(false);

    expect(sent.url).toBe("https://gateway.example/agents/ada/logs");
    expect(sent.url).not.toContain("token");
    expect(sent.authorization).toBe("Bearer access-token");
    expect(sent.events).toEqual([
      { kind: "line", text: "hello" },
      { kind: "end" },
    ]);
  });

  it("asks for no tail on a reconnect, still with the header", async () => {
    const sent = await streamAgentLogs(true);

    expect(sent.url).toBe("https://gateway.example/agents/ada/logs?tail=0");
    expect(sent.url).not.toContain("token");
    expect(sent.authorization).toBe("Bearer access-token");
  });
});
