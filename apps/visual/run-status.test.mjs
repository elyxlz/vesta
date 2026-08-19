import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  currentRunStatus,
  liveStatuses,
  publishRunStatus,
  runStatusPath,
} from "./run-status.mjs";

describe("liveStatuses", () => {
  const ios = {
    state: "ready",
    runner: "ios",
    updatedAt: "2026-08-18T10:00:00.000Z",
  };
  const android = {
    state: "capturing",
    runner: "android",
    updatedAt: "2026-08-18T10:00:05.000Z",
    pid: 4242,
  };
  it("orders newest first and keeps every live runner", () => {
    expect(liveStatuses([ios, android], () => true)).toEqual([android, ios]);
  });
  it("reports a capturing entry whose runner died as stopped", () => {
    const dead = { ...android, pid: 424242 };
    expect(liveStatuses([ios, dead], () => false)).toEqual([
      {
        ...dead,
        state: "error",
        message: "android capture stopped",
        detail: "The runner exited before it finished.",
      },
      ios,
    ]);
  });
  it("ignores an entry without a timestamp", () => {
    expect(liveStatuses([null, { state: "ready" }, ios], () => true)).toEqual([
      ios,
    ]);
  });
});

describe("publishRunStatus and currentRunStatus", () => {
  it("writes one file per runner so two runners never overwrite each other", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-status-"));
    await publishRunStatus(
      "capturing",
      {
        runner: "android",
        message: "Building",
        startedAt: "2026-08-18T10:00:00.000Z",
      },
      base,
    );
    await publishRunStatus(
      "ready",
      { runner: "ios", message: "Captured 49 iOS screenshots" },
      base,
    );
    const written = JSON.parse(
      await readFile(runStatusPath("android", base), "utf8"),
    );
    expect(written).toMatchObject({
      state: "capturing",
      runner: "android",
      message: "Building",
      detail: "",
    });
    const { statuses } = await currentRunStatus(base);
    expect(statuses.map((status) => status.runner)).toEqual(["ios", "android"]);
    expect(statuses.find((status) => status.runner === "android").state).toBe(
      "capturing",
    );
  });

  it("requires a runner", async () => {
    await expect(publishRunStatus("ready", {}, os.tmpdir())).rejects.toThrow(
      /needs its runner/,
    );
  });

  it("skips files it cannot parse", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-status-"));
    await writeFile(path.join(base, "run-status-web.json"), "{not json");
    await publishRunStatus("ready", { runner: "ios" }, base);
    const { statuses } = await currentRunStatus(base);
    expect(statuses.map((status) => status.runner)).toEqual(["ios"]);
  });
});
