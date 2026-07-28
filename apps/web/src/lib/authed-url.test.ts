import { describe, expect, it, vi, beforeEach } from "vitest";

const mocks = vi.hoisted(() => ({
  connection: null as { url: string; accessToken: string } | null,
  refreshes: 0,
}));

vi.mock("@/lib/connection", () => ({
  getConnection: () => mocks.connection,
}));
vi.mock("@/lib/token-refresh", () => ({
  ensureFreshToken: () => {
    mocks.refreshes += 1;
    return Promise.resolve("ok");
  },
}));

const { mediaUrl, websocketUrl } = await import("@/lib/authed-url");

beforeEach(() => {
  mocks.connection = { url: "https://h", accessToken: "tok" };
  mocks.refreshes = 0;
});

describe("authed urls", () => {
  it("stamps the token into a media URL over http", async () => {
    await expect(mediaUrl("/agents/agent/voice/tts/stream/id")).resolves.toBe(
      "https://h/agents/agent/voice/tts/stream/id?token=tok",
    );
  });

  it("swaps the scheme for a socket URL", async () => {
    mocks.connection = { url: "https://h", accessToken: "tok" };
    await expect(websocketUrl("/sync")).resolves.toBe("wss://h/sync?token=tok");
  });

  it("percent-encodes a token with url-unsafe characters", async () => {
    mocks.connection = { url: "https://h", accessToken: "a b+c" };
    await expect(mediaUrl("/x")).resolves.toBe("https://h/x?token=a+b%2Bc");
  });

  it("keeps caller query params alongside the token", async () => {
    await expect(
      mediaUrl("/agents/agent/logs", new URLSearchParams({ tail: "0" })),
    ).resolves.toBe("https://h/agents/agent/logs?tail=0&token=tok");
  });

  it("refreshes an expiring token before handing out any URL", async () => {
    await websocketUrl("/sync");
    expect(mocks.refreshes).toBe(1);
  });

  it("rejects when there is no connection", async () => {
    mocks.connection = null;
    await expect(websocketUrl("/sync")).rejects.toThrow(
      "not connected to vestad",
    );
  });
});
