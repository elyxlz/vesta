import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  clearConnection,
  clearRecentGateways,
  readConnection,
  readRecentGateways,
  storageBackendIsSecure,
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
  delete process.env.VESTA_TEST_ENCRYPTION_AVAILABLE;
  delete process.env.VESTA_TEST_STORAGE_BACKEND;
  await fs.rm(userDataDir, { recursive: true, force: true });
});

describe("secure storage availability", () => {
  it.each<[string, string, boolean, string, boolean]>([
    [
      "rejects an unavailable encryption service",
      "darwin",
      false,
      "unknown",
      false,
    ],
    [
      "rejects Electron's Linux plaintext fallback",
      "linux",
      true,
      "basic_text",
      false,
    ],
    ["rejects an unknown Linux backend", "linux", true, "unknown", false],
    ["accepts a Linux secret store", "linux", true, "gnome_libsecret", true],
    ["accepts Keychain encryption", "darwin", true, "unknown", true],
    ["accepts DPAPI encryption", "win32", true, "unknown", true],
  ])("%s", (_name, platform, available, backend, expected) => {
    expect(storageBackendIsSecure(platform, available, backend)).toBe(expected);
  });

  it("rejects writes when encryption is unavailable", async () => {
    process.env.VESTA_TEST_ENCRYPTION_AVAILABLE = "false";

    await expect(writeConnection(CONNECTION)).rejects.toThrow(
      "secure credential storage is unavailable",
    );
  });
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
