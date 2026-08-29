import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentStatus } from "@vesta/core";
import { apiJson } from "./client";
import { waitUntilAlive, waitUntilRunning } from "./agents";

vi.mock("./client", () => ({
  apiJson: vi.fn(),
  apiFetch: vi.fn(),
  jsonInit: vi.fn(),
}));

const apiJsonMock = vi.mocked(apiJson);
const POLL_MS = 500;

// Each poll answers the next status; the last one repeats for any further polls.
function statuses(...sequence: AgentStatus[]): void {
  let index = 0;
  apiJsonMock.mockImplementation(() => {
    const status = sequence[Math.min(index, sequence.length - 1)];
    index += 1;
    return Promise.resolve({ status });
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("waitUntilAlive", () => {
  it("resolves once the agent reports alive, polling through the boot", async () => {
    statuses("starting", "starting", "alive");
    const waiting = waitUntilAlive("ada", 10_000, POLL_MS);
    await vi.advanceTimersByTimeAsync(POLL_MS * 2);
    await expect(waiting).resolves.toBeUndefined();
    expect(apiJsonMock).toHaveBeenCalledTimes(3);
  });

  it.each<AgentStatus>(["stopped", "not_authenticated", "unprovisioned"])(
    "fails fast on %s instead of waiting out the timeout",
    async (status) => {
      statuses("starting", status);
      const waiting = waitUntilAlive("ada", 10_000, POLL_MS);
      const outcome = waiting.catch((e: unknown) => e);
      await vi.advanceTimersByTimeAsync(POLL_MS);
      expect(await outcome).toEqual(new Error(`ada: ${status}`));
    },
  );

  it("times out with a named reason when the agent never settles", async () => {
    statuses("starting");
    const waiting = waitUntilAlive("ada", 2_000, POLL_MS);
    const outcome = waiting.catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(2_000 + POLL_MS);
    expect(await outcome).toEqual(
      new Error("ada: timed out waiting to become alive"),
    );
  });
});

describe("waitUntilRunning", () => {
  it("treats a waiting-on-user status as ready, since the HTTP server is up", async () => {
    statuses("starting", "unprovisioned");
    const waiting = waitUntilRunning("ada", 10_000, POLL_MS);
    await vi.advanceTimersByTimeAsync(POLL_MS);
    await expect(waiting).resolves.toBeUndefined();
  });
});
