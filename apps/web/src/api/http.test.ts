import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LogEvent } from "@/lib/types";
import { restoreConnection } from "@/lib/connection";
import { ApiError, httpClient } from "./client";
import { streamGatewayLogs, streamLogs } from "./logs";

// The web session is @vesta/core's over the connection store; these pin the web-side wiring:
// the one http client stamps the stored token, and the log streams read through it.
type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

const fetchMock = vi.fn<Fetch>();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  restoreConnection({
    url: "https://gateway.example",
    accessToken: "access-token",
    refreshToken: "refresh",
    expiresAt: Date.now() + 60 * 60 * 1000,
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

async function thrownBy(promise: Promise<unknown>): Promise<ApiError> {
  const thrown: unknown = await promise.catch((e: unknown) => e);
  if (!(thrown instanceof ApiError)) throw new Error("expected ApiError");
  return thrown;
}

describe("httpClient", () => {
  it("throws an ApiError carrying the status and the server's error message", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ error: "agent not found" }), {
        status: 404,
      }),
    );
    const error = await thrownBy(httpClient.request("/agents/missing"));
    expect(error.status).toBe(404);
    expect(error.message).toBe("agent not found");
  });

  it("stamps the stored token as a Bearer header on the gateway URL", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
    await httpClient.request("/agents");
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("https://gateway.example/agents");
    expect(new Headers(init?.headers).get("Authorization")).toBe(
      "Bearer access-token",
    );
  });
});

function sseResponse(body: string): Response {
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("log streams", () => {
  it("read the agent log SSE through the authenticated client and map its events", async () => {
    fetchMock.mockResolvedValue(
      sseResponse("data: hello\n\nevent: agent_stopped\ndata: \n\n"),
    );
    const events: LogEvent[] = [];
    await streamLogs("ada", (event) => events.push(event));
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toContain("/agents/ada/logs?tail=");
    expect(new Headers(init?.headers).get("Authorization")).toBe(
      "Bearer access-token",
    );
    expect(events).toEqual([{ kind: "Line", text: "hello" }, { kind: "End" }]);
  });

  it("read the gateway log SSE with follow when asked", async () => {
    fetchMock.mockResolvedValue(
      sseResponse("event: gateway_stopped\ndata: \n\n"),
    );
    const events: LogEvent[] = [];
    await streamGatewayLogs(true, (event: LogEvent) => events.push(event));
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "https://gateway.example/gateway/logs?follow=true",
    );
    expect(events).toEqual([{ kind: "End" }]);
  });
});
