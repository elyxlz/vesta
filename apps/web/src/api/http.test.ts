import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LogEvent } from "@/lib/types";
import { apiFetch, ApiError } from "./client";
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

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
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

describe("apiFetch", () => {
  it("throws an ApiError carrying the status and the server's error message", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ error: "agent 'luna' already exists" }), {
        status: 409,
      }),
    );
    const error = await thrownBy(apiFetch("/agents", { method: "POST" }));
    expect(error.status).toBe(409);
    expect(error.message).toBe("agent 'luna' already exists");
  });

  it("falls back to the raw body when the error response is not json", async () => {
    fetchMock.mockResolvedValue(new Response("boom", { status: 500 }));
    const error = await thrownBy(apiFetch("/agents"));
    expect(error.status).toBe(500);
    expect(error.message).toBe("boom");
  });

  it("returns the response untouched on success", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
    const resp = await apiFetch("/agents");
    expect(resp.status).toBe(200);
  });
});

describe("log streams", () => {
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

  it("agent logs present the access token as a header, never in the URL", async () => {
    fetchMock.mockResolvedValue(streamEnding("agent_stopped"));
    const events: LogEvent[] = [];

    await streamLogs("ada", (event) => events.push(event));

    const { url, authorization } = sentRequest();
    expect(url).toBe("https://box.example/agents/ada/logs?tail=5000");
    expect(url).not.toContain("token");
    expect(authorization).toBe("Bearer access-token");
    expect(events).toEqual([{ kind: "Line", text: "hello" }, { kind: "End" }]);
  });

  it("gateway logs present the access token as a header, never in the URL", async () => {
    fetchMock.mockResolvedValue(streamEnding("gateway_stopped"));

    await streamGatewayLogs(true, () => undefined);

    const { url, authorization } = sentRequest();
    expect(url).toBe("https://box.example/gateway/logs?follow=true");
    expect(url).not.toContain("token");
    expect(authorization).toBe("Bearer access-token");
  });
});
