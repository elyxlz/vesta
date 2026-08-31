import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentStatus } from "@vesta/core";
import { apiJson } from "./client";
import { AgentStatusError, waitUntilReady, waitUntilRunning } from "./agents";

vi.mock("./client", () => ({
  apiJson: vi.fn(),
  apiFetch: vi.fn(),
  jsonInit: vi.fn(),
}));

const apiJsonMock = vi.mocked(apiJson);
const POLL_MS = 500;

// Each poll answers the next status; the last one repeats for any further polls.
function statuses(
  ...sequence: { status: AgentStatus; booting?: boolean }[]
): void {
  let index = 0;
  apiJsonMock.mockImplementation(() => {
    const response = sequence[Math.min(index, sequence.length - 1)];
    index += 1;
    return Promise.resolve(response);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("waitUntilReady", () => {
  it("keeps the onboarding shell mounted until alive finishes booting", async () => {
    statuses(
      { status: "starting" },
      { status: "alive", booting: true },
      { status: "alive" },
      { status: "alive", booting: false },
    );
    const waiting = waitUntilReady("ada", 10_000, POLL_MS);
    await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    await expect(waiting).resolves.toBeUndefined();
    expect(apiJsonMock).toHaveBeenCalledTimes(4);
  });

  it.each<AgentStatus>(["stopped", "not_authenticated", "unprovisioned"])(
    "fails fast on %s instead of waiting out the timeout",
    async (status) => {
      statuses({ status: "starting" }, { status });
      const waiting = waitUntilReady("ada", 10_000, POLL_MS);
      const outcome = waiting.catch((e: unknown) => e);
      await vi.advanceTimersByTimeAsync(POLL_MS);
      const error = await outcome;
      expect(error).toBeInstanceOf(AgentStatusError);
      expect(error).toMatchObject({ status });
      expect(error).toHaveProperty("message", `ada: ${status}`);
    },
  );

  it("times out with a named reason when the agent never settles", async () => {
    statuses({ status: "starting" });
    const waiting = waitUntilReady("ada", 2_000, POLL_MS);
    const outcome = waiting.catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(2_000 + POLL_MS);
    expect(await outcome).toEqual(
      new Error("ada: timed out waiting to become ready"),
    );
  });
});

describe("waitUntilRunning", () => {
  it("treats a waiting-on-user status as ready, since the HTTP server is up", async () => {
    statuses({ status: "starting" }, { status: "unprovisioned" });
    const waiting = waitUntilRunning("ada", 10_000, POLL_MS);
    await vi.advanceTimersByTimeAsync(POLL_MS);
    await expect(waiting).resolves.toBeUndefined();
  });
});
