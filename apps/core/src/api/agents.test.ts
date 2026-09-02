import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RESTART_REASONS, restartBody } from "../lifecycle/restart-reasons";
import type { AgentStatus } from "../protocol/tree";
import type { HttpClient } from "../transport/http";
import {
  AgentStatusError,
  renameAgent,
  restartAgent,
  waitUntilReady,
  waitUntilRunning,
} from "./agents";

const POLL_MS = 500;

function http() {
  const json = vi.fn<(path: string, init?: RequestInit) => Promise<unknown>>();
  const request = vi
    .fn<HttpClient["request"]>()
    .mockResolvedValue(new Response());
  const client: HttpClient = { json: json as HttpClient["json"], request };
  return { client, json, request };
}

// Each poll answers the next status; the last one repeats for any further polls.
function statuses(
  json: ReturnType<typeof http>["json"],
  ...sequence: { status: AgentStatus; booting?: boolean }[]
): void {
  let index = 0;
  json.mockImplementation(() => {
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
});

describe("waitUntilReady", () => {
  it("keeps the onboarding shell mounted until alive finishes booting", async () => {
    const { client, json } = http();
    statuses(
      json,
      { status: "starting" },
      { status: "alive", booting: true },
      { status: "alive" },
      { status: "alive", booting: false },
    );
    const waiting = waitUntilReady(client, "ada", 10_000, POLL_MS);
    await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    await expect(waiting).resolves.toBeUndefined();
    expect(json).toHaveBeenCalledTimes(4);
    expect(json).toHaveBeenCalledWith("/agents/ada");
  });

  it.each<AgentStatus>(["stopped", "not_authenticated", "unprovisioned"])(
    "fails fast on %s instead of waiting out the timeout",
    async (status) => {
      const { client, json } = http();
      statuses(json, { status: "starting" }, { status });
      const waiting = waitUntilReady(client, "ada", 10_000, POLL_MS);
      const outcome = waiting.catch((e: unknown) => e);
      await vi.advanceTimersByTimeAsync(POLL_MS);
      const error = await outcome;
      expect(error).toBeInstanceOf(AgentStatusError);
      expect(error).toMatchObject({ status });
      expect(error).toHaveProperty("message", `ada: ${status}`);
    },
  );

  it("times out with a named reason when the agent never settles", async () => {
    const { client, json } = http();
    statuses(json, { status: "starting" });
    const waiting = waitUntilReady(client, "ada", 2_000, POLL_MS);
    const outcome = waiting.catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(2_000 + POLL_MS);
    expect(await outcome).toEqual(
      new Error("ada: timed out waiting to become ready"),
    );
  });
});

describe("waitUntilRunning", () => {
  it("treats a waiting-on-user status as ready, since the HTTP server is up", async () => {
    const { client, json } = http();
    statuses(json, { status: "starting" }, { status: "unprovisioned" });
    const waiting = waitUntilRunning(client, "ada", 10_000, POLL_MS);
    await vi.advanceTimersByTimeAsync(POLL_MS);
    await expect(waiting).resolves.toBeUndefined();
  });
});

describe("restartAgent", () => {
  it("sends no body for a plain manual restart, leaving vestad to name it", async () => {
    const { client, request } = http();
    await restartAgent(client, "luna");
    expect(request).toHaveBeenCalledWith("/agents/luna/restart", {
      method: "POST",
    });
  });

  it("sends the restart reason token as the JSON body", async () => {
    const { client, request } = http();
    await restartAgent(client, "luna", RESTART_REASONS.model);
    const [path, init] = request.mock.calls[0] ?? [];
    expect(path).toBe("/agents/luna/restart");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual(
      restartBody(RESTART_REASONS.model),
    );
  });
});

describe("renameAgent", () => {
  it("PATCHes the new name and returns the normalized one vestad chose", async () => {
    const { client, json } = http();
    json.mockResolvedValue({ name: "luna-2" });
    await expect(renameAgent(client, "Luna 2", "luna-2")).resolves.toBe(
      "luna-2",
    );
    expect(json).toHaveBeenCalledWith(
      "/agents/Luna%202",
      expect.objectContaining({ method: "PATCH" }),
    );
  });
});
