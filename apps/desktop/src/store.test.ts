import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearConnection, readConnection, writeConnection } from "./store";

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
  });

  it("reads null when nothing has been written", async () => {
    expect(await readConnection()).toBeNull();
  });

  it("reads null rather than throwing on a corrupt store file", async () => {
    await fs.writeFile(path.join(userDataDir, "connection.json"), "{ not json");
    expect(await readConnection()).toBeNull();
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
