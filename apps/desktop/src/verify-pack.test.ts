import { createPackage } from "@electron/asar";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import verifyPack, { type VerifyPackContext } from "../scripts/verify-pack.mjs";

// verify-pack is the afterPack guard that fails the build when the packed app is broken. Two
// releases shipped past config-only checks: one dropped node_modules from the asar, one shipped an
// un-bundled preload. This drives the guard against real asars built each way.

const BUNDLED_PRELOAD = 'contextBridge.exposeInMainWorld("vestaNative", {});\n';
const TSC_PRELOAD =
  'const c = require("./channels");\nexposeInMainWorld("vestaNative", {});\n';

const dirs: string[] = [];
afterEach(() => {
  for (const dir of dirs.splice(0))
    fs.rmSync(dir, { recursive: true, force: true });
});

async function packApp(
  preload: string,
  withNodeModules: boolean,
): Promise<string> {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "verify-pack-"));
  dirs.push(root);
  const src = path.join(root, "src");
  fs.mkdirSync(path.join(src, "dist-electron"), { recursive: true });
  fs.writeFileSync(path.join(src, "dist-electron", "preload.js"), preload);
  if (withNodeModules) {
    const dep = path.join(src, "node_modules", "electron-updater");
    fs.mkdirSync(dep, { recursive: true });
    fs.writeFileSync(path.join(dep, "index.js"), "module.exports = {};\n");
  }
  const resources = path.join(root, "Vesta.app", "Contents", "Resources");
  fs.mkdirSync(resources, { recursive: true });
  await createPackage(src, path.join(resources, "app.asar"));
  return root;
}

const context = (appOutDir: string): VerifyPackContext => ({
  electronPlatformName: "darwin",
  appOutDir,
  packager: { appInfo: { productFilename: "Vesta" } },
});

describe("verify-pack afterPack guard", () => {
  it("passes a well-formed package", async () => {
    const out = await packApp(BUNDLED_PRELOAD, true);
    expect(() => verifyPack(context(out))).not.toThrow();
  });

  it("fails when node_modules was dropped from the asar", async () => {
    const out = await packApp(BUNDLED_PRELOAD, false);
    expect(() => verifyPack(context(out))).toThrow(/node_modules/);
  });

  it("fails when the preload is not bundled", async () => {
    const out = await packApp(TSC_PRELOAD, true);
    expect(() => verifyPack(context(out))).toThrow(/not bundled/);
  });
});
