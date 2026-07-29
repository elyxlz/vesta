import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LogEvent } from "@/lib/types";
import { streamGatewayLogs } from "./gateway";
import { streamLogs } from "./logs";

vi.mock("@/lib/connection", () => ({
  getConnection: () => ({
    url: "https://box.example",
    accessToken: "access-token",
    refreshToken: "refresh",
    expiresAt: Date.now() + 60 * 60 * 1000,
  }),
  isTokenExpiringSoon: () => false,
}));
vi.mock("@/lib/token-refresh", () => ({
  ensureFreshToken: vi.fn().mockResolvedValue("ok"),
}));

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

const fetchMock = vi.fn<Fetch>();

function streamEnding(stoppedEvent: string): Response {
  return new Response(`data: hello\n\nevent: ${stoppedEvent}\ndata: \n\n`);
}

// The one request the stream made: its URL and the headers it presented.
function sentRequest(): { url: string; authorization: string | null } {
  const call = fetchMock.mock.calls[0];
  if (!call) throw new Error("expected the log stream to send a request");
  const [url, init] = call;
  return {
    url,
    authorization: new Headers(init?.headers).get("Authorization"),
  };
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("agent log stream", () => {
  it("presents the access token as a header, never in the URL", async () => {
    fetchMock.mockResolvedValue(streamEnding("agent_stopped"));
    const events: LogEvent[] = [];

    await streamLogs("ada", (event) => events.push(event));

    const { url, authorization } = sentRequest();
    expect(url).toBe("https://box.example/agents/ada/logs?tail=5000");
    expect(url).not.toContain("token");
    expect(authorization).toBe("Bearer access-token");
    expect(events).toEqual([{ kind: "Line", text: "hello" }, { kind: "End" }]);
  });
});

describe("gateway log stream", () => {
  it("presents the access token as a header, never in the URL", async () => {
    fetchMock.mockResolvedValue(streamEnding("gateway_stopped"));

    await streamGatewayLogs(true, () => undefined);

    const { url, authorization } = sentRequest();
    expect(url).toBe("https://box.example/gateway/logs?follow=true");
    expect(url).not.toContain("token");
    expect(authorization).toBe("Bearer access-token");
  });
});
