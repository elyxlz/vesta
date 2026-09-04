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
});
