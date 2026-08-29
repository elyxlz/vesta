import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  clearConnection,
  clearRecentGateways,
  readConnection,
  readRecentGateways,
  writeConnection,
  writeRecentGateways,
} from "./store";

const CONNECTION = { url: "https://box.example", accessToken: "at" };

let userDataDir = "";

beforeEach(async () => {
  userDataDir = await fs.mkdtemp(path.join(os.tmpdir(), "vesta-store-test-"));
  process.env.VESTA_TEST_USER_DATA = userDataDir;
});

afterEach(async () => {
  delete process.env.VESTA_TEST_USER_DATA;
  await fs.rm(userDataDir, { recursive: true, force: true });
});

describe("connection store", () => {
  it("round-trips a written connection", async () => {
    await writeConnection(CONNECTION);
    expect(await readConnection()).toEqual(CONNECTION);
    const stored = await fs.readFile(
      path.join(userDataDir, "connection.json"),
      "utf8",
    );
    expect(stored).not.toContain(CONNECTION.accessToken);
  });

  it("reads null when nothing has been written", async () => {
    expect(await readConnection()).toBeNull();
  });

  it("reads null rather than throwing on a corrupt store file", async () => {
    await fs.writeFile(path.join(userDataDir, "connection.json"), "{ not json");
    expect(await readConnection()).toBeNull();
  });

  it("migrates a plaintext connection to encrypted storage", async () => {
    const target = path.join(userDataDir, "connection.json");
    await fs.writeFile(target, JSON.stringify(CONNECTION));

    expect(await readConnection()).toEqual(CONNECTION);
    expect(await fs.readFile(target, "utf8")).not.toContain(
      CONNECTION.accessToken,
    );
  });

  it("clears a stored connection", async () => {
    await writeConnection(CONNECTION);
    await clearConnection();
    expect(await readConnection()).toBeNull();
  });

  it("clears an absent connection without throwing", async () => {
    await expect(clearConnection()).resolves.toBeUndefined();
  });
});

describe("recent gateway store", () => {
  it("round-trips encrypted saved gateways", async () => {
    const gateways = [{ connection: CONNECTION, lastConnectedAt: 1 }];
    await writeRecentGateways(gateways);

    expect(await readRecentGateways()).toEqual(gateways);
    const stored = await fs.readFile(
      path.join(userDataDir, "recent-gateways.json"),
      "utf8",
    );
    expect(stored).not.toContain(CONNECTION.accessToken);
  });

  it("clears saved gateways", async () => {
    await writeRecentGateways([]);
    await clearRecentGateways();
    expect(await readRecentGateways()).toBeNull();
  });
});
