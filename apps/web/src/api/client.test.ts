import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiFetch, ApiError } from "./client";

vi.mock("@/lib/connection", () => ({
  apiUrl: (path: string) => `https://box.example${path}`,
  authHeaders: () => ({ Authorization: "Bearer token" }),
}));
vi.mock("@/lib/token-refresh", () => ({
  ensureFreshToken: vi.fn().mockResolvedValue("ok"),
}));

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("apiFetch", () => {
  it("throws an ApiError carrying the status and the server's error message", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ error: "agent 'luna' already exists" }), {
        status: 409,
      }),
    );
    const thrown: unknown = await apiFetch("/agents", { method: "POST" }).catch(
      (e: unknown) => e,
    );
    if (!(thrown instanceof ApiError)) throw new Error("expected ApiError");
    expect(thrown.status).toBe(409);
    expect(thrown.message).toBe("agent 'luna' already exists");
  });

  it("falls back to the raw body when the error response is not json", async () => {
    fetchMock.mockResolvedValue(new Response("boom", { status: 500 }));
    const thrown: unknown = await apiFetch("/agents").catch((e: unknown) => e);
    if (!(thrown instanceof ApiError)) throw new Error("expected ApiError");
    expect(thrown.status).toBe(500);
    expect(thrown.message).toBe("boom");
  });

  it("returns the response untouched on success", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
    const resp = await apiFetch("/agents");
    expect(resp.status).toBe(200);
  });
});
