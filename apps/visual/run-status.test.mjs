import { mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  STALE_CAPTURING_MS,
  newerRunStatus,
  publishRunStatus,
} from "./run-status.mjs";

describe("newerRunStatus", () => {
  const server = { state: "ready", updatedAt: "2026-08-18T10:00:00.000Z" };
  it("serves the file status when a capture wrote it more recently", () => {
    const file = {
      state: "capturing",
      updatedAt: "2026-08-18T10:00:05.000Z",
      runner: "ios",
    };
    expect(newerRunStatus(server, file, Date.parse(file.updatedAt))).toBe(file);
  });
  it("keeps the server status when the file is older or absent", () => {
    const file = { state: "ready", updatedAt: "2026-08-18T09:00:00.000Z" };
    expect(newerRunStatus(server, file, Date.now())).toBe(server);
    expect(newerRunStatus(server, null, Date.now())).toBe(server);
  });
  it("ignores a capturing entry a hard-killed run left behind", () => {
    const file = { state: "capturing", updatedAt: "2026-08-18T10:00:05.000Z" };
    const later = Date.parse(file.updatedAt) + STALE_CAPTURING_MS + 1;
    expect(newerRunStatus(server, file, later)).toBe(server);
  });
});

describe("publishRunStatus", () => {
  it("writes the phase with its runner to the status file", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-status-"));
    const target = path.join(base, "run-status.json");
    await publishRunStatus(
      "capturing",
      {
        message: "Preparing",
        startedAt: "2026-08-18T10:00:00.000Z",
        runner: "web",
      },
      target,
    );
    const written = JSON.parse(await readFile(target, "utf8"));
    expect(written).toMatchObject({
      state: "capturing",
      message: "Preparing",
      runner: "web",
      detail: "",
    });
    expect(typeof written.updatedAt).toBe("string");
  });
});
