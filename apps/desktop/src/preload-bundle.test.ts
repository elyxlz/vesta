import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// The preload runs in a sandboxed renderer (sandbox: true), whose require() resolves only
// electron and a few Node built-ins, never a relative file. So the compiled preload must be a
// single self-contained bundle: a surviving require("./...") throws before exposeInMainWorld
// runs, window.vestaNative stays undefined, and the app silently falls back to the browser
// bridge. This checks the real compile pipeline, not the bundler in isolation.
const DESKTOP_ROOT = path.resolve(__dirname, "..");
const PRELOAD_JS = path.join(DESKTOP_ROOT, "dist-electron", "preload.js");
const RELATIVE_IMPORT = /(?:require\(|from\s*)["']\.\.?\//;

describe("compiled preload", () => {
  it("is a self-contained bundle the sandbox can load", () => {
    execFileSync("npm", ["run", "compile"], { cwd: DESKTOP_ROOT });
    const bundle = fs.readFileSync(PRELOAD_JS, "utf8");
    expect(bundle).toContain('exposeInMainWorld("vestaNative"');
    expect(bundle).not.toMatch(RELATIVE_IMPORT);
  }, 120_000);

  // CI packages with `npx tsc` + `npx electron-builder`, never `npm run compile`, so the bundling
  // must run inside a build hook. beforePack, not beforeBuild: beforeBuild is the dependency-install
  // hook and defining it drops node_modules from the asar. verify-pack (afterPack) then fails the
  // build if either the preload or node_modules is missing. Lock both hooks here.
  it("wires preload bundling and artifact verification into electron-builder", () => {
    const config = fs.readFileSync(
      path.join(DESKTOP_ROOT, "electron-builder.yml"),
      "utf8",
    );
    expect(config).toMatch(/^beforePack:\s*scripts\/before-pack\.mjs\s*$/m);
    expect(config).toMatch(/^afterPack:\s*scripts\/verify-pack\.mjs\s*$/m);
    expect(config).not.toMatch(/^beforeBuild:/m);
  });
});
