# Visual QA Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One deterministic screenshot system and one gallery cover every Vesta client: mobile (iOS, Android gesture, Android 3-button), web (light and dark), and desktop (the web screens in the Electron window).

**Architecture:** A new workspace package `apps/visual/` (`@vesta/visual`) owns the platform table, the registry contract, the shot store, run status, and the gallery server. The mobile runners (Maestro) and the web runner (Playwright) each keep their own capture code and write into the shared store. The gallery composes both registries plus the store per request.

**Tech Stack:** Node 22 ESM (`.mjs`, no build), vitest, eslint (`@eslint/js` + `globals`), Playwright (`@playwright/test` ^1.62), Maestro, `npm` workspaces.

**Spec:** `docs/superpowers/specs/2026-08-18-visual-qa-unification-design.md`

## Global Constraints

- Work in the worktree `/Users/epasca/vesta-worktrees/epic-apps`, branch `epic/apps`. Never push to master. Never force push.
- Commit after each task with a Conventional Commits subject, no trailing period, and this trailer:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_018fd5pKXDG52mzAG2LaCfFz
  ```
- No lint or type-checker escapes anywhere (`eslint-disable`, `@ts-ignore`, `@ts-expect-error`, `# noqa`). Comment blocks are capped at 8 lines.
- Prose in READMEs, SKILL.md, and PR text: no dashes as separators; use commas, periods, or colons. Never use a pronoun for Vesta.
- Nothing visual-capture-related enters `apps/mobile/app/`, `apps/mobile/src/`, `apps/web/src/`, or `apps/desktop/src/`.
- Platform ids are exactly: `ios`, `android`, `android-galaxy`, `web`, `desktop`, `web-narrow`, `web-dark`, `desktop-dark`, `web-narrow-dark`. Runner ids: `ios`, `android`, `android-galaxy`, `web`. Family ids: `mobile`, `web`.
- The gallery port is 4173, bound to `127.0.0.1`. The store is `apps/visual/.visual/`.
- Watch mode is removed everywhere. Serving lives only in `@vesta/visual`.
- All `npm` commands run from `apps/` unless a step says otherwise. Run `npm install` in `apps/` after any `package.json` change.
- Existing function names are kept when code only moves; rename only where the old name is mobile-specific.

---

## File map

Created:
- `apps/visual/package.json`, `apps/visual/eslint.config.mjs`, `apps/visual/vitest.config.mjs`
- `apps/visual/platforms.mjs`, `apps/visual/platforms.d.mts`, `apps/visual/platforms.test.mjs`
- `apps/visual/store.mjs`, `apps/visual/store.d.mts`, `apps/visual/store.test.mjs`
- `apps/visual/run-status.mjs`, `apps/visual/run-status.test.mjs`
- `apps/visual/registry.mjs`, `apps/visual/registry.d.mts`, `apps/visual/registry.test.mjs`
- `apps/visual/gallery/view.mjs`, `apps/visual/gallery/page.mjs`, `apps/visual/gallery/styles.css`, `apps/visual/gallery/client.js`, `apps/visual/gallery/view.test.mjs`
- `apps/visual/gallery/server.mjs`, `apps/visual/gallery/server.test.mjs`, `apps/visual/cli.mjs`
- `apps/visual/README.md`, `apps/visual/.agents/skills/visual-qa/SKILL.md`, `apps/visual/.agents/skills/visual-qa/agents/openai.yaml`
- `.claude/skills/visual-qa/SKILL.md`
- `apps/mobile/scripts/visual-runner.mjs`, `apps/mobile/scripts/visual-runner.test.mjs`
- `apps/web/visual/scenarios.json`, `apps/web/visual/drives.ts`, `apps/web/visual/registry.test.ts`, `apps/web/visual/harness/native-stub.ts`

Renamed (git mv):
- `apps/mobile/scripts/visual-catalog.mjs` -> `apps/mobile/scripts/visual-ios.mjs` (and its test)
- `apps/mobile/scripts/visual-catalog-android.mjs` -> `apps/mobile/scripts/visual-android.mjs` (and its test)

Deleted:
- `apps/web/visual/gallery.mjs`, `apps/web/visual/test-options.ts`, `apps/web/visual/global-setup.ts`, `apps/web/visual/scenarios.ts`
- `apps/mobile/.agents/skills/mobile-visual-qa/` (whole directory), `.claude/skills/mobile-visual-qa/` (whole directory)

Modified:
- `apps/package.json`, `apps/.gitignore`, `.gitignore`, `check.sh`, `.github/workflows/ci.yml`
- `apps/mobile/package.json`, `apps/mobile/maestro/visual/capture-screenshot.js`, `apps/mobile/visual/README.md`
- `apps/web/package.json`, `apps/web/visual/playwright.config.ts`, `apps/web/visual/capture.spec.ts`, `apps/web/visual/README.md`
- `.claude/workflows/product-critique.js`

---

### Task 1: Scaffold `@vesta/visual` with the platform table

**Files:**
- Create: `apps/visual/package.json`, `apps/visual/eslint.config.mjs`, `apps/visual/vitest.config.mjs`, `apps/visual/platforms.mjs`, `apps/visual/platforms.d.mts`
- Test: `apps/visual/platforms.test.mjs`
- Modify: `apps/package.json` (workspaces), `apps/.gitignore`, `.gitignore`

**Interfaces:**
- Produces: `PLATFORMS`, `RUNNERS`, `FAMILIES`, `platformFamily(id)`, `platformsOfFamily(family)`, `runnerOf(platform)`, `appsRoot` (absolute path of `apps/`), `visualRoot` (absolute path of `apps/visual/`) from `@vesta/visual/platforms`.

- [ ] **Step 1: Create the package manifest, lint, and test configs**

`apps/visual/package.json`:
```json
{
  "name": "@vesta/visual",
  "private": true,
  "version": "0.0.0",
  "description": "Vesta visual QA: the shared platform table, registry contract, shot store, and gallery for every app",
  "type": "module",
  "exports": {
    "./platforms": { "types": "./platforms.d.mts", "default": "./platforms.mjs" },
    "./registry": { "types": "./registry.d.mts", "default": "./registry.mjs" },
    "./store": { "types": "./store.d.mts", "default": "./store.mjs" },
    "./run-status": "./run-status.mjs"
  },
  "scripts": {
    "serve": "node cli.mjs serve",
    "capture": "node cli.mjs capture",
    "lint": "eslint .",
    "test": "vitest run"
  },
  "devDependencies": {
    "@eslint/js": "^10.0.1",
    "eslint": "^10.7.0",
    "globals": "^17.11.0",
    "vitest": "^4.1.10"
  }
}
```

`apps/visual/eslint.config.mjs`:
```js
import js from "@eslint/js";
import globals from "globals";
import { defineConfig, globalIgnores } from "eslint/config";

export default defineConfig([
  globalIgnores([".visual"]),
  {
    files: ["**/*.mjs"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
  {
    files: ["gallery/client.js"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.browser },
  },
]);
```

`apps/visual/vitest.config.mjs`:
```js
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { include: ["**/*.test.mjs"], exclude: ["node_modules/**", ".visual/**"] },
});
```

- [ ] **Step 2: Register the workspace and ignore the store**

In `apps/package.json` change `"workspaces"` to:
```json
  "workspaces": [
    "web",
    "desktop",
    "core",
    "mobile",
    "visual"
  ],
```

In `apps/.gitignore` replace the last line `mobile/.visual/` with:
```
mobile/.visual/
web/.visual/
visual/.visual/
```

In the root `.gitignore` delete these two lines:
```
# Web visual harness output
apps/web/.visual/
```

Run: `cd apps && npm install`
Expected: `node_modules/@vesta/visual` is a symlink to `../../visual`.

- [ ] **Step 3: Write the failing platform tests**

`apps/visual/platforms.test.mjs`:
```js
import { describe, expect, it } from "vitest";
import {
  FAMILIES,
  PLATFORMS,
  RUNNERS,
  platformFamily,
  platformsOfFamily,
  runnerOf,
} from "./platforms.mjs";

describe("PLATFORMS", () => {
  it("names every platform once with a family, a theme, a frame, and a runner", () => {
    for (const [id, platform] of Object.entries(PLATFORMS)) {
      expect(id).toMatch(/^[a-z]+(?:-[a-z]+)*$/);
      expect(Object.keys(FAMILIES)).toContain(platform.family);
      expect(["light", "dark"]).toContain(platform.theme);
      expect(["phone", "browser", "desktop-window", "phone-browser"]).toContain(platform.frame);
      expect(Object.keys(RUNNERS)).toContain(platform.runner);
      expect(platform.label).toBeTruthy();
    }
  });

  it("orders each family light before dark so a card wraps light row over dark row", () => {
    for (const family of Object.keys(FAMILIES)) {
      const themes = platformsOfFamily(family).map((platform) => PLATFORMS[platform].theme);
      const firstDark = themes.indexOf("dark");
      if (firstDark === -1) continue;
      expect(themes.slice(firstDark).every((theme) => theme === "dark")).toBe(true);
    }
  });
});

describe("RUNNERS", () => {
  it("every runner captures at least one platform", () => {
    for (const runner of Object.keys(RUNNERS)) {
      const served = Object.values(PLATFORMS).filter((platform) => platform.runner === runner);
      expect(served.length).toBeGreaterThan(0);
    }
  });

  it("names the workspace script a scan spawns and how gentle mode reaches it", () => {
    expect(RUNNERS.ios).toMatchObject({
      workspace: "@vesta/mobile",
      script: "visual:ios:capture",
      gentleArgs: ["--gentle"],
    });
    expect(RUNNERS["android-galaxy"].args).toEqual(["--variant", "android-galaxy"]);
    expect(RUNNERS.web).toMatchObject({
      workspace: "@vesta/web",
      script: "visual:capture",
      gentleArgs: ["--workers=2"],
    });
  });
});

describe("lookups", () => {
  it("resolves family, platforms, and runner by id", () => {
    expect(platformFamily("android-galaxy")).toBe("mobile");
    expect(platformFamily("desktop-dark")).toBe("web");
    expect(platformsOfFamily("mobile")).toEqual(["ios", "android", "android-galaxy"]);
    expect(platformsOfFamily("web")).toEqual([
      "web",
      "desktop",
      "web-narrow",
      "web-dark",
      "desktop-dark",
      "web-narrow-dark",
    ]);
    expect(runnerOf("web-narrow-dark")).toBe("web");
  });

  it("rejects an unknown platform id", () => {
    expect(() => platformFamily("windows")).toThrow(/Unknown platform: windows/);
  });
});
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd apps && npm -w @vesta/visual run test`
Expected: FAIL, `Cannot find module './platforms.mjs'`.

- [ ] **Step 5: Write `platforms.mjs` and its declaration file**

`apps/visual/platforms.mjs`:
```js
import { fileURLToPath } from "node:url";
import path from "node:path";

export const visualRoot = path.dirname(fileURLToPath(import.meta.url));
export const appsRoot = path.resolve(visualRoot, "..");

// The one owner of which capture targets exist. A platform is one gallery slot:
// a theme variant is its own platform the same way the 3-button Android persona is.
// Runner-only facts (an AVD, a viewport, a native stub) live in the runner, keyed by id.
export const PLATFORMS = {
  ios: { label: "iOS", family: "mobile", theme: "light", frame: "phone", runner: "ios" },
  android: { label: "Android", family: "mobile", theme: "light", frame: "phone", runner: "android" },
  "android-galaxy": {
    label: "Android · 3-button",
    family: "mobile",
    theme: "light",
    frame: "phone",
    runner: "android-galaxy",
  },
  web: { label: "Web", family: "web", theme: "light", frame: "browser", runner: "web" },
  desktop: { label: "Desktop", family: "web", theme: "light", frame: "desktop-window", runner: "web" },
  "web-narrow": { label: "Web · phone", family: "web", theme: "light", frame: "phone-browser", runner: "web" },
  "web-dark": { label: "Web · dark", family: "web", theme: "dark", frame: "browser", runner: "web" },
  "desktop-dark": {
    label: "Desktop · dark",
    family: "web",
    theme: "dark",
    frame: "desktop-window",
    runner: "web",
  },
  "web-narrow-dark": {
    label: "Web · phone · dark",
    family: "web",
    theme: "dark",
    frame: "phone-browser",
    runner: "web",
  },
};

// What a gallery Scan button (or `cli.mjs capture <runner>`) spawns from apps/:
// `npm -w <workspace> run <script> -- [...args] [...gentleArgs]`. reportDirectory
// is the runner's own HTML report, served by the gallery under /reports/<runner>/.
export const RUNNERS = {
  ios: {
    label: "iOS",
    workspace: "@vesta/mobile",
    script: "visual:ios:capture",
    args: [],
    gentleArgs: ["--gentle"],
    reportDirectory: path.join(appsRoot, "mobile/.visual/maestro"),
  },
  android: {
    label: "Android",
    workspace: "@vesta/mobile",
    script: "visual:android:capture",
    args: [],
    gentleArgs: ["--gentle"],
    reportDirectory: path.join(appsRoot, "mobile/.visual/android/maestro"),
  },
  "android-galaxy": {
    label: "Android · 3-button",
    workspace: "@vesta/mobile",
    script: "visual:android:capture",
    args: ["--variant", "android-galaxy"],
    gentleArgs: ["--gentle"],
    reportDirectory: path.join(appsRoot, "mobile/.visual/android-galaxy/maestro"),
  },
  web: {
    label: "Web",
    workspace: "@vesta/web",
    script: "visual:capture",
    args: [],
    gentleArgs: ["--workers=2"],
    reportDirectory: path.join(appsRoot, "web/.visual/report"),
  },
};

export const FAMILIES = {
  mobile: { label: "Mobile", registry: path.join(appsRoot, "mobile/visual/scenarios.json") },
  web: { label: "Web", registry: path.join(appsRoot, "web/visual/scenarios.json") },
};

function requirePlatform(id) {
  const platform = PLATFORMS[id];
  if (!platform) throw new Error(`Unknown platform: ${id}`);
  return platform;
}

export function platformFamily(id) {
  return requirePlatform(id).family;
}

export function runnerOf(id) {
  return requirePlatform(id).runner;
}

export function platformsOfFamily(family) {
  return Object.keys(PLATFORMS).filter((id) => PLATFORMS[id].family === family);
}
```

`apps/visual/platforms.d.mts`:
```ts
export type PlatformId =
  | "ios"
  | "android"
  | "android-galaxy"
  | "web"
  | "desktop"
  | "web-narrow"
  | "web-dark"
  | "desktop-dark"
  | "web-narrow-dark";
export type RunnerId = "ios" | "android" | "android-galaxy" | "web";
export type FamilyId = "mobile" | "web";
export type Theme = "light" | "dark";
export type Frame = "phone" | "browser" | "desktop-window" | "phone-browser";

export interface PlatformDefinition {
  label: string;
  family: FamilyId;
  theme: Theme;
  frame: Frame;
  runner: RunnerId;
}
export interface RunnerDefinition {
  label: string;
  workspace: string;
  script: string;
  args: string[];
  gentleArgs: string[];
  reportDirectory: string;
}
export interface FamilyDefinition {
  label: string;
  registry: string;
}

export const visualRoot: string;
export const appsRoot: string;
export const PLATFORMS: Record<PlatformId, PlatformDefinition>;
export const RUNNERS: Record<RunnerId, RunnerDefinition>;
export const FAMILIES: Record<FamilyId, FamilyDefinition>;
export function platformFamily(id: string): FamilyId;
export function runnerOf(id: string): RunnerId;
export function platformsOfFamily(family: FamilyId): PlatformId[];
```

- [ ] **Step 6: Run the tests and lint to verify they pass**

Run: `cd apps && npm -w @vesta/visual run test && npm -w @vesta/visual run lint`
Expected: 6 tests PASS, lint clean.

- [ ] **Step 7: Commit**

```bash
git add apps/visual apps/package.json apps/package-lock.json apps/.gitignore .gitignore
git commit -m "feat(visual): scaffold @vesta/visual with the platform table"
```

---

### Task 2: The shot store

**Files:**
- Create: `apps/visual/store.mjs`, `apps/visual/store.d.mts`
- Test: `apps/visual/store.test.mjs`
- Reference: `apps/mobile/scripts/visual-catalog.mjs:1233-1243` (`pngSize`), `:1281-1320` (`shotEntries`, `shotDriftWarning`), `:379-387` (`atomicWriteFile`), `apps/mobile/scripts/visual-catalog-android.mjs:640-646` (the tmp+rename copy).

**Interfaces:**
- Consumes: `PLATFORMS`, `visualRoot` from Task 1.
- Produces from `@vesta/visual/store`: `storeDirectory` (= `apps/visual/.visual`), `shotsDirectory` (= `apps/visual/.visual/shots`), `platformShotsDirectory(platform)`, `putShot(platform, name, sourcePath)`, `shotEntries(baseDirectory = storeDirectory)`, `pngSize(filePath)`, `shotDriftWarning(producedNames, scenarios)`, `atomicWriteFile(target, contents)`.

- [ ] **Step 1: Write the failing store tests**

`apps/visual/store.test.mjs`:
```js
import { mkdir, mkdtemp, readdir, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  atomicWriteFile,
  platformShotsDirectory,
  pngSize,
  putShot,
  shotDriftWarning,
  shotEntries,
  shotsDirectory,
} from "./store.mjs";

// A minimal 1x2 PNG header: signature, IHDR length, "IHDR", width 1, height 2.
function pngHeader(width, height) {
  const buffer = Buffer.alloc(24);
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(buffer, 0);
  buffer.writeUInt32BE(13, 8);
  buffer.write("IHDR", 12, "ascii");
  buffer.writeUInt32BE(width, 16);
  buffer.writeUInt32BE(height, 20);
  return buffer;
}

describe("paths", () => {
  it("keys the store by platform id under apps/visual/.visual/shots", () => {
    expect(platformShotsDirectory("web-dark")).toBe(path.join(shotsDirectory, "web-dark"));
    expect(shotsDirectory.endsWith(path.join("apps", "visual", ".visual", "shots"))).toBe(true);
  });
});

describe("putShot", () => {
  it("copies a shot into the platform directory and leaves no temp file behind", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-store-"));
    const source = path.join(base, "source.png");
    await writeFile(source, pngHeader(1, 2));
    await putShot("ios", "home.png", source, base);
    const target = path.join(base, "shots", "ios");
    expect(await readdir(target)).toEqual(["home.png"]);
    expect((await readFile(path.join(target, "home.png"))).equals(pngHeader(1, 2))).toBe(true);
  });

  it("rejects a name that is not a bare .png filename", async () => {
    await expect(putShot("ios", "../home.png", "/dev/null")).rejects.toThrow(/Invalid shot name/);
    await expect(putShot("ios", "home.jpg", "/dev/null")).rejects.toThrow(/Invalid shot name/);
  });

  it("rejects an unknown platform", async () => {
    await expect(putShot("tv", "home.png", "/dev/null")).rejects.toThrow(/Unknown platform: tv/);
  });
});

describe("shotEntries", () => {
  it("indexes shot files per platform with store-relative sources", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-store-"));
    await mkdir(path.join(base, "shots", "ios"), { recursive: true });
    await mkdir(path.join(base, "shots", "web-dark"), { recursive: true });
    await writeFile(path.join(base, "shots", "ios", "home.png"), pngHeader(1, 2));
    await writeFile(path.join(base, "shots", "ios", "notes.txt"), "ignored");
    await writeFile(path.join(base, "shots", "web-dark", "done.png"), pngHeader(3, 4));
    const entries = await shotEntries(base);
    expect(Object.keys(entries.ios)).toEqual(["home.png"]);
    expect(entries.ios["home.png"].src).toBe("shots/ios/home.png");
    expect(typeof entries.ios["home.png"].mtime).toBe("number");
    expect(entries["web-dark"]["done.png"].src).toBe("shots/web-dark/done.png");
    expect(entries.android).toEqual({});
  });

  it("serves every platform empty while the store does not exist", async () => {
    const entries = await shotEntries(path.join(os.tmpdir(), "visual-store-missing"));
    expect(Object.keys(entries).sort()).toEqual(
      ["android", "android-galaxy", "desktop", "desktop-dark", "ios", "web", "web-dark", "web-narrow", "web-narrow-dark"],
    );
    expect(Object.values(entries).every((entry) => Object.keys(entry).length === 0)).toBe(true);
  });
});

describe("pngSize", () => {
  it("reads the IHDR dimensions and rejects a non-PNG", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-store-"));
    await writeFile(path.join(base, "a.png"), pngHeader(640, 480));
    await writeFile(path.join(base, "b.png"), "not a png at all, just text");
    expect(await pngSize(path.join(base, "a.png"))).toEqual({ width: 640, height: 480 });
    expect(await pngSize(path.join(base, "b.png"))).toBeNull();
  });
});

describe("shotDriftWarning", () => {
  const scenarios = [{ screenshot: "a.png" }, { screenshot: "b.png" }];
  it("is empty when the produced shots match the registry", () => {
    expect(shotDriftWarning(new Set(["a.png", "b.png"]), scenarios)).toBe("");
  });
  it("names missing and unexpected shots without refusing the run", () => {
    expect(shotDriftWarning(new Set(["a.png", "z.png"]), scenarios)).toBe(
      "missing: b.png; unexpected: z.png",
    );
  });
});

describe("atomicWriteFile", () => {
  it("writes through a temp file and leaves only the target", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-store-"));
    const target = path.join(base, "nested", "status.json");
    await atomicWriteFile(target, "{}\n");
    expect(await readFile(target, "utf8")).toBe("{}\n");
    expect(await readdir(path.dirname(target))).toEqual(["status.json"]);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps && npm -w @vesta/visual run test -- store`
Expected: FAIL, `Cannot find module './store.mjs'`.

- [ ] **Step 3: Write `store.mjs`**

```js
import { copyFile, mkdir, readdir, readFile, rename, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { PLATFORMS, visualRoot } from "./platforms.mjs";

// The one shot store: one PNG per scenario per platform, replaced in place as a
// scan captures it, so a failed or partial run leaves the entries it did not reach untouched.
export const storeDirectory = path.join(visualRoot, ".visual");
export const shotsDirectory = path.join(storeDirectory, "shots");

export function platformShotsDirectory(platform, baseDirectory = storeDirectory) {
  if (!PLATFORMS[platform]) throw new Error(`Unknown platform: ${platform}`);
  return path.join(baseDirectory, "shots", platform);
}

let temporaryFileCounter = 0;

export async function atomicWriteFile(target, contents) {
  await mkdir(path.dirname(target), { recursive: true });
  temporaryFileCounter += 1;
  const temporary = `${target}.${process.pid}.${temporaryFileCounter}.tmp`;
  await writeFile(temporary, contents);
  await rename(temporary, target);
}

// The only writer of shot files: copy to a temp name in the target directory, then
// rename, so the gallery's poll never reads a torn PNG.
export async function putShot(platform, name, sourcePath, baseDirectory = storeDirectory) {
  if (typeof name !== "string" || path.basename(name) !== name || !name.endsWith(".png")) {
    throw new Error(`Invalid shot name: ${name}`);
  }
  const directory = platformShotsDirectory(platform, baseDirectory);
  await mkdir(directory, { recursive: true });
  const target = path.join(directory, name);
  const temporary = `${target}.tmp-${process.pid}`;
  await copyFile(sourcePath, temporary);
  await rename(temporary, target);
}

// Index of the shot files on disk: platform -> filename -> {src, mtime}, with src
// relative to the store root so the page can load and cache-bust it.
export async function shotEntries(baseDirectory = storeDirectory) {
  const platforms = Object.keys(PLATFORMS);
  const entries = Object.fromEntries(platforms.map((platform) => [platform, {}]));
  for (const platform of platforms) {
    const directory = path.join(baseDirectory, "shots", platform);
    let names = [];
    try {
      names = await readdir(directory);
    } catch {
      continue;
    }
    for (const name of names) {
      if (!name.endsWith(".png")) continue;
      try {
        const mtime = Math.round((await stat(path.join(directory, name))).mtimeMs);
        entries[platform][name] = { src: `shots/${platform}/${name}`, mtime };
      } catch {
        continue;
      }
    }
  }
  return entries;
}

export async function pngSize(filePath) {
  const file = await readFile(filePath);
  if (
    file.length < 24 ||
    file.toString("ascii", 1, 4) !== "PNG" ||
    file.toString("ascii", 12, 16) !== "IHDR"
  ) {
    return null;
  }
  return { width: file.readUInt32BE(16), height: file.readUInt32BE(20) };
}

// A scan warns about registry drift instead of refusing: the shot files it
// replaced stay valid either way.
export function shotDriftWarning(producedNames, scenarios) {
  const expected = scenarios.map((scenario) => scenario.screenshot);
  const missing = expected.filter((name) => !producedNames.has(name));
  const unexpected = [...producedNames].filter((name) => !expected.includes(name)).sort();
  const parts = [];
  if (missing.length > 0) parts.push(`missing: ${missing.join(", ")}`);
  if (unexpected.length > 0) parts.push(`unexpected: ${unexpected.join(", ")}`);
  return parts.join("; ");
}
```

`apps/visual/store.d.mts`:
```ts
export const storeDirectory: string;
export const shotsDirectory: string;
export function platformShotsDirectory(platform: string, baseDirectory?: string): string;
export function atomicWriteFile(target: string, contents: string): Promise<void>;
export function putShot(platform: string, name: string, sourcePath: string, baseDirectory?: string): Promise<void>;
export function shotEntries(baseDirectory?: string): Promise<Record<string, Record<string, { src: string; mtime: number }>>>;
export function pngSize(filePath: string): Promise<{ width: number; height: number } | null>;
export function shotDriftWarning(producedNames: Set<string>, scenarios: { screenshot: string }[]): string;
```

- [ ] **Step 4: Run tests and lint**

Run: `cd apps && npm -w @vesta/visual run test && npm -w @vesta/visual run lint`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/visual/store.mjs apps/visual/store.d.mts apps/visual/store.test.mjs
git commit -m "feat(visual): add the shared shot store with one atomic writer"
```

---

### Task 3: Run status

**Files:**
- Create: `apps/visual/run-status.mjs`
- Test: `apps/visual/run-status.test.mjs`
- Reference: `apps/mobile/scripts/visual-catalog.mjs:114-180` and the `newerRunStatus` tests at `apps/mobile/scripts/visual-catalog.test.mjs:88-120`.

**Interfaces:**
- Consumes: `storeDirectory`, `atomicWriteFile` from Task 2.
- Produces from `@vesta/visual/run-status`: `publishRunStatus(state, options)`, `currentRunStatus()`, `newerRunStatus(serverStatus, fileStatus, now)`, `STALE_CAPTURING_MS`, `runStatusPath`. The status object is `{ state, message, detail, startedAt, runner, updatedAt }`. The field is `runner` (a runner id), replacing the old `platform`.

- [ ] **Step 1: Write the failing tests**

`apps/visual/run-status.test.mjs`:
```js
import { mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { STALE_CAPTURING_MS, newerRunStatus, publishRunStatus } from "./run-status.mjs";

describe("newerRunStatus", () => {
  const server = { state: "ready", updatedAt: "2026-08-18T10:00:00.000Z" };
  it("serves the file status when a capture wrote it more recently", () => {
    const file = { state: "capturing", updatedAt: "2026-08-18T10:00:05.000Z", runner: "ios" };
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
    await publishRunStatus("capturing", { message: "Preparing", startedAt: "2026-08-18T10:00:00.000Z", runner: "web" }, target);
    const written = JSON.parse(await readFile(target, "utf8"));
    expect(written).toMatchObject({ state: "capturing", message: "Preparing", runner: "web", detail: "" });
    expect(typeof written.updatedAt).toBe("string");
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps && npm -w @vesta/visual run test -- run-status`
Expected: FAIL, module not found.

- [ ] **Step 3: Write `run-status.mjs`**

```js
import { readFile } from "node:fs/promises";
import path from "node:path";
import { atomicWriteFile, storeDirectory } from "./store.mjs";

// A capture runs in its own process, so its progress crosses to the gallery on disk:
// each phase is written here and /status.json serves whichever of the server's own
// state and the file is newer. A "capturing" entry a hard-killed run left behind goes
// stale after the cutoff instead of showing a phantom run forever.
export const runStatusPath = path.join(storeDirectory, "run-status.json");
export const STALE_CAPTURING_MS = 45 * 60 * 1000;

// The initial state carries the epoch, not boot time: a restarted server must not
// outrank the last phase an in-flight capture wrote to the file.
let serverStatus = {
  state: "ready",
  message: "Screenshots are up to date",
  detail: "",
  startedAt: null,
  runner: null,
  updatedAt: new Date(0).toISOString(),
};

export async function publishRunStatus(state, options = {}, target = runStatusPath) {
  serverStatus = {
    state,
    message: options.message ?? "",
    detail: options.detail ?? "",
    startedAt: options.startedAt ?? null,
    runner: options.runner ?? null,
    updatedAt: new Date().toISOString(),
  };
  await atomicWriteFile(target, `${JSON.stringify(serverStatus)}\n`);
}

export function newerRunStatus(server, fileStatus, now) {
  if (!fileStatus?.updatedAt) return server;
  if (fileStatus.state === "capturing" && now - Date.parse(fileStatus.updatedAt) > STALE_CAPTURING_MS) {
    return server;
  }
  return fileStatus.updatedAt > server.updatedAt ? fileStatus : server;
}

export async function currentRunStatus(target = runStatusPath) {
  let fileStatus = null;
  try {
    fileStatus = JSON.parse(await readFile(target, "utf8"));
  } catch {
    fileStatus = null;
  }
  return newerRunStatus(serverStatus, fileStatus, Date.now());
}
```

- [ ] **Step 4: Run tests and lint**

Run: `cd apps && npm -w @vesta/visual run test && npm -w @vesta/visual run lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/visual/run-status.mjs apps/visual/run-status.test.mjs
git commit -m "feat(visual): move capture run status into the shared store"
```

---

### Task 4: The registry contract

**Files:**
- Create: `apps/visual/registry.mjs`, `apps/visual/registry.d.mts`
- Test: `apps/visual/registry.test.mjs`
- Reference: `apps/mobile/scripts/visual-catalog.mjs:474-544` (`scenarioOnPlatform`, `loadManifest`), `:1322-1327` (`excludedNote`).

**Interfaces:**
- Consumes: `FAMILIES`, `PLATFORMS`, `platformsOfFamily`, `appsRoot` from Task 1.
- Produces from `@vesta/visual/registry`:
  - `validateRegistry(manifest, family, options)` returns the normalised registry `{ ...manifest, family, scenarios }` where every scenario carries `family` and a filled `screenshot`. `options.flowRoot` (absolute dir) enables flow existence checks; when `flows` is present it is validated against it.
  - `loadRegistry(family)` reads `FAMILIES[family].registry`, validates, and returns the registry.
  - `loadAllRegistries()` loads every family and rejects duplicate ids or screenshot names across families; returns `{ mobile, web }`.
  - `scenarioOnPlatform(scenario, platform)`; `scenariosForPlatform(registry, platform)`; `excludedNote(scenario)`.

- [ ] **Step 1: Write the failing tests**

`apps/visual/registry.test.mjs`:
```js
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  excludedNote,
  loadAllRegistries,
  loadRegistry,
  scenarioOnPlatform,
  scenariosForPlatform,
  validateRegistry,
} from "./registry.mjs";

const scenario = (overrides) => ({ id: "home", title: "Home", description: "d", group: "Home", ...overrides });

describe("validateRegistry", () => {
  it("normalises a family's scenarios: family tag and screenshot default", () => {
    const registry = validateRegistry({ version: 1, scenarios: [scenario({})] }, "web");
    expect(registry.family).toBe("web");
    expect(registry.scenarios[0]).toMatchObject({ id: "home", family: "web", screenshot: "home.png" });
  });

  it("keeps an explicit screenshot name and passes family state through", () => {
    const registry = validateRegistry(
      { version: 1, scenarios: [scenario({ screenshot: "start.png", route: "/new", agentStatus: "alive" })] },
      "web",
    );
    expect(registry.scenarios[0]).toMatchObject({ screenshot: "start.png", route: "/new", agentStatus: "alive" });
  });

  it("rejects a bad version, id, screenshot, or a platform outside the family", () => {
    expect(() => validateRegistry({ version: 2, scenarios: [scenario({})] }, "web")).toThrow(/version/);
    expect(() => validateRegistry({ version: 1, scenarios: [scenario({ id: "Bad_Id" })] }, "web")).toThrow(/Invalid visual scenario id/);
    expect(() => validateRegistry({ version: 1, scenarios: [scenario({ screenshot: "x.jpg" })] }, "web")).toThrow(/Invalid screenshot name/);
    expect(() => validateRegistry({ version: 1, scenarios: [scenario({ platforms: ["ios"] })] }, "web")).toThrow(/Invalid platforms for home/);
    expect(() => validateRegistry({ version: 1, scenarios: [scenario({}), scenario({})] }, "web")).toThrow(/Duplicate visual scenario id/);
    expect(() => validateRegistry({ version: 1, scenarios: [scenario({ title: "" })] }, "web")).toThrow(/title/);
  });

  it("requires flows for the mobile family and checks each exists under flowRoot", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "visual-registry-"));
    await mkdir(path.join(root, "maestro"), { recursive: true });
    await writeFile(path.join(root, "maestro/a.yml"), "appId: x\n");
    const manifest = { version: 1, appId: "app", flows: ["maestro/a.yml"], scenarios: [scenario({})] };
    expect(() => validateRegistry(manifest, "mobile", { flowRoot: root })).not.toThrow();
    expect(() => validateRegistry({ ...manifest, flows: ["maestro/missing.yml"] }, "mobile", { flowRoot: root })).toThrow(/does not exist/);
    expect(() => validateRegistry({ ...manifest, flows: ["../escape.yml"] }, "mobile", { flowRoot: root })).toThrow(/escapes/);
    expect(() => validateRegistry({ version: 1, scenarios: [scenario({})] }, "mobile", { flowRoot: root })).toThrow(/at least one flow/);
  });
});

describe("platform filtering", () => {
  it("includes a scenario on every family platform unless it restricts itself", () => {
    expect(scenarioOnPlatform(scenario({ family: "mobile" }), "android-galaxy")).toBe(true);
    expect(scenarioOnPlatform(scenario({ family: "mobile", platforms: ["ios"] }), "android")).toBe(false);
    expect(scenarioOnPlatform(scenario({ family: "web", platforms: ["web", "desktop"] }), "web-dark")).toBe(false);
  });
  it("filters a registry to one platform", () => {
    const registry = validateRegistry(
      { version: 1, scenarios: [scenario({}), scenario({ id: "phone-only", platforms: ["web-narrow"] })] },
      "web",
    );
    expect(scenariosForPlatform(registry, "web").map((entry) => entry.id)).toEqual(["home"]);
    expect(scenariosForPlatform(registry, "web-narrow").map((entry) => entry.id)).toEqual(["home", "phone-only"]);
  });
  it("labels an exclusion with the platform labels it kept", () => {
    expect(excludedNote(scenario({ platforms: ["ios"] }))).toBe("iOS only");
    expect(excludedNote(scenario({ platforms: ["web", "desktop"] }))).toBe("Web + Desktop only");
  });
});

describe("loadRegistry and loadAllRegistries", () => {
  it("loads both shipped registries and finds no cross-family collision", async () => {
    const all = await loadAllRegistries();
    expect(all.mobile.family).toBe("mobile");
    expect(all.web.family).toBe("web");
    expect(all.mobile.scenarios.length).toBeGreaterThan(0);
    expect(all.web.scenarios.length).toBeGreaterThan(0);
  });
  it("loads one family by name", async () => {
    const registry = await loadRegistry("mobile");
    expect(registry.flows.length).toBeGreaterThan(0);
    expect(registry.scenarios.every((entry) => entry.screenshot.endsWith(".png"))).toBe(true);
  });
});
```

Note: the last describe block reads the real `scenarios.json` files. It fails until Task 8 creates `apps/web/visual/scenarios.json`. Run the other blocks now with `-t "validateRegistry|platform filtering"`; the whole file passes after Task 8.

- [ ] **Step 2: Run to verify failure**

Run: `cd apps && npm -w @vesta/visual run test -- registry -t "validateRegistry|platform filtering"`
Expected: FAIL, module not found.

- [ ] **Step 3: Write `registry.mjs`**

```js
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { FAMILIES, PLATFORMS, platformsOfFamily } from "./platforms.mjs";

const SCENARIO_ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function requireText(scenario, field) {
  if (typeof scenario[field] !== "string" || !scenario[field].trim()) {
    throw new Error(`Visual scenario ${scenario.id ?? "?"} needs a ${field}.`);
  }
}

// One contract for every family: card data the gallery reads, plus whatever state
// the family's runner needs, passed through untouched.
export function validateRegistry(manifest, family, options = {}) {
  if (!FAMILIES[family]) throw new Error(`Unknown family: ${family}`);
  if (manifest.version !== 1) {
    throw new Error(`Unsupported visual registry version: ${manifest.version}`);
  }
  if (!Array.isArray(manifest.scenarios) || manifest.scenarios.length === 0) {
    throw new Error("The visual registry must define at least one scenario.");
  }
  const familyPlatforms = platformsOfFamily(family);
  const ids = new Set();
  const screenshots = new Set();
  const scenarios = manifest.scenarios.map((entry) => {
    if (!SCENARIO_ID.test(entry.id ?? "")) {
      throw new Error(`Invalid visual scenario id: ${entry.id}`);
    }
    if (ids.has(entry.id)) throw new Error(`Duplicate visual scenario id: ${entry.id}`);
    requireText(entry, "title");
    requireText(entry, "description");
    requireText(entry, "group");
    const screenshot = entry.screenshot ?? `${entry.id}.png`;
    if (path.basename(screenshot) !== screenshot || path.extname(screenshot) !== ".png") {
      throw new Error(`Invalid screenshot name for ${entry.id}.`);
    }
    if (screenshots.has(screenshot)) throw new Error(`Duplicate screenshot name: ${screenshot}`);
    if (
      "platforms" in entry &&
      (!Array.isArray(entry.platforms) ||
        entry.platforms.length === 0 ||
        entry.platforms.some((name) => !familyPlatforms.includes(name)))
    ) {
      throw new Error(`Invalid platforms for ${entry.id}.`);
    }
    ids.add(entry.id);
    screenshots.add(screenshot);
    return { ...entry, family, screenshot };
  });
  if (family === "mobile") {
    if (!Array.isArray(manifest.flows) || manifest.flows.length === 0) {
      throw new Error("The mobile visual registry must define at least one flow.");
    }
    if (typeof manifest.appId !== "string" || !manifest.appId) {
      throw new Error("The mobile visual registry must define appId.");
    }
    const flowRoot = options.flowRoot ?? path.dirname(path.dirname(FAMILIES.mobile.registry));
    for (const flow of manifest.flows) {
      const flowPath = path.resolve(flowRoot, flow);
      if (!flowPath.startsWith(`${flowRoot}${path.sep}`)) {
        throw new Error(`Flow escapes the mobile workspace: ${flow}`);
      }
      if (!existsSync(flowPath)) throw new Error(`Visual flow does not exist: ${flow}`);
    }
  }
  return { ...manifest, family, scenarios };
}

export async function loadRegistry(family) {
  if (!FAMILIES[family]) throw new Error(`Unknown family: ${family}`);
  const manifest = JSON.parse(await readFile(FAMILIES[family].registry, "utf8"));
  return validateRegistry(manifest, family);
}

// The gallery composes every family into one page, so an id or a screenshot name
// must be unique across families too, or one card would overwrite another.
export async function loadAllRegistries() {
  const registries = {};
  const seenIds = new Map();
  const seenShots = new Map();
  for (const family of Object.keys(FAMILIES)) {
    registries[family] = await loadRegistry(family);
    for (const scenario of registries[family].scenarios) {
      const idOwner = seenIds.get(scenario.id);
      if (idOwner) throw new Error(`Scenario id ${scenario.id} exists in both ${idOwner} and ${family}.`);
      const shotOwner = seenShots.get(scenario.screenshot);
      if (shotOwner) throw new Error(`Screenshot ${scenario.screenshot} exists in both ${shotOwner} and ${family}.`);
      seenIds.set(scenario.id, family);
      seenShots.set(scenario.screenshot, family);
    }
  }
  return registries;
}

export function scenarioOnPlatform(scenario, platform) {
  return !Array.isArray(scenario.platforms) || scenario.platforms.includes(platform);
}

export function scenariosForPlatform(registry, platform) {
  return registry.scenarios.filter((scenario) => scenarioOnPlatform(scenario, platform));
}

export function excludedNote(scenario) {
  const labels = (scenario.platforms ?? []).map((platform) => PLATFORMS[platform]?.label ?? platform);
  return `${labels.join(" + ")} only`;
}
```

`apps/visual/registry.d.mts`:
```ts
import type { FamilyId, PlatformId } from "./platforms.d.mts";

export interface RegistryScenario {
  id: string;
  title: string;
  description: string;
  group: string;
  screenshot: string;
  family: FamilyId;
  platforms?: PlatformId[];
  [state: string]: unknown;
}
export interface Registry {
  version: 1;
  family: FamilyId;
  appId?: string;
  flows?: string[];
  scenarios: RegistryScenario[];
}
export function validateRegistry(manifest: unknown, family: FamilyId, options?: { flowRoot?: string }): Registry;
export function loadRegistry(family: FamilyId): Promise<Registry>;
export function loadAllRegistries(): Promise<Record<FamilyId, Registry>>;
export function scenarioOnPlatform(scenario: { platforms?: string[] }, platform: string): boolean;
export function scenariosForPlatform(registry: Registry, platform: string): RegistryScenario[];
export function excludedNote(scenario: { platforms?: string[] }): string;
```

- [ ] **Step 4: Run the two runnable describe blocks and lint**

Run: `cd apps && npm -w @vesta/visual run test -- registry -t "validateRegistry|platform filtering" && npm -w @vesta/visual run lint`
Expected: PASS (the `loadRegistry` block is expected to fail until Task 8).

- [ ] **Step 5: Commit**

```bash
git add apps/visual/registry.mjs apps/visual/registry.d.mts apps/visual/registry.test.mjs
git commit -m "feat(visual): add the shared scenario registry contract"
```

---

### Task 5: The gallery view, page, styles, and client

**Files:**
- Create: `apps/visual/gallery/view.mjs`, `apps/visual/gallery/page.mjs`, `apps/visual/gallery/styles.css`, `apps/visual/gallery/client.js`
- Test: `apps/visual/gallery/view.test.mjs`
- Reference (move sources): `apps/mobile/scripts/visual-catalog.mjs:1245-1260` (`gitMetadata`), `:1262-1268` (`escapeHtml`), `:1331-1443` (`galleryView`, `slotHtml`, sections and cards), `:1444-1466` (report links, scan rows, gentle toggle), `:1473-1849` (CSS), `:1851-1874` (body), `:1875-2120` (script), `:2125-2155` (`composeGallery`). Tests to move: `apps/mobile/scripts/visual-catalog.test.mjs:303-443` (`galleryView`, `galleryHtml`, `shotEntries`).

**Interfaces:**
- Consumes: `PLATFORMS`, `RUNNERS`, `FAMILIES`, `platformsOfFamily`, `visualRoot` (Task 1); `shotEntries`, `pngSize`, `storeDirectory` (Task 2); `loadAllRegistries`, `scenarioOnPlatform`, `excludedNote` (Task 4).
- Produces: `galleryView(scenarios, shots, options)`, `galleryHtml(view)`, `composeGallery()`, `frameHtml(frame, screenHtml)`, `escapeHtml(value)`. The view model:
  ```
  { git: {revision, dirty}, reports: [{label, href}],
    sections: [{ key, family, familyLabel, group, scenarios: [{ id, title, description, group, screenshot, family, slots: [slot] }] }] }
  slot = { platform, label, frame, theme, state: "excluded"|"missing"|"captured", note?, src?, mtime?, size? }
  ```
  `page.mjs` reads `styles.css` at import; the server serves `styles.css` and `client.js` as static files at `/gallery/styles.css` and `/gallery/client.js` (Task 6).

- [ ] **Step 1: Write the failing view tests**

`apps/visual/gallery/view.test.mjs`:
```js
import { describe, expect, it } from "vitest";
import { frameHtml, galleryView } from "./view.mjs";
import { galleryHtml } from "./page.mjs";

const mobileScenario = { id: "home", title: "Home", description: "The home screen.", group: "Home", screenshot: "home.png", family: "mobile" };
const webScenario = { id: "name-empty", title: "Empty name", description: "The name step.", group: "Onboarding", screenshot: "name-empty.png", family: "web" };
const shots = {
  ios: { "home.png": { src: "shots/ios/home.png", mtime: 1000, size: { width: 603, height: 1311 } } },
  web: { "name-empty.png": { src: "shots/web/name-empty.png", mtime: 2000, size: null } },
};

describe("galleryView", () => {
  it("renders one slot per family platform for every scenario", () => {
    const view = galleryView([mobileScenario, webScenario], shots);
    const [mobile, web] = view.sections;
    expect(mobile.scenarios[0].slots.map((slot) => slot.platform)).toEqual(["ios", "android", "android-galaxy"]);
    expect(web.scenarios[0].slots.map((slot) => slot.platform)).toEqual([
      "web", "desktop", "web-narrow", "web-dark", "desktop-dark", "web-narrow-dark",
    ]);
  });

  it("keys sections by family and group in registry order, mobile first", () => {
    const view = galleryView([webScenario, mobileScenario], shots);
    expect(view.sections.map((section) => section.key)).toEqual(["Mobile · Home", "Web · Onboarding"]);
    expect(view.sections[0]).toMatchObject({ family: "mobile", familyLabel: "Mobile", group: "Home" });
  });

  it("fills a captured slot from its shot entry and marks the rest", () => {
    const view = galleryView([mobileScenario], shots);
    const [ios, android] = view.sections[0].scenarios[0].slots;
    expect(ios).toMatchObject({ state: "captured", src: "shots/ios/home.png", mtime: 1000, frame: "phone", theme: "light" });
    expect(android).toMatchObject({ state: "missing", note: "Not captured yet" });
  });

  it("marks a platform-excluded scenario apart from a missing shot", () => {
    const view = galleryView([{ ...webScenario, platforms: ["web"] }], shots);
    const slots = view.sections[0].scenarios[0].slots;
    expect(slots[0].state).toBe("captured");
    expect(slots[1]).toMatchObject({ state: "excluded", note: "Web only" });
  });
});

describe("frameHtml", () => {
  it("wraps the screen in the chrome its frame names", () => {
    expect(frameHtml("phone", "<i>s</i>")).toContain('class="frame frame-phone"');
    expect(frameHtml("browser", "<i>s</i>")).toContain('class="browser-bar"');
    expect(frameHtml("desktop-window", "<i>s</i>")).toContain('class="titlebar"');
    expect(frameHtml("phone-browser", "<i>s</i>")).toContain('class="frame frame-phone frame-phone-browser"');
    expect(frameHtml("phone", "<i>s</i>")).toContain("<i>s</i>");
  });
});

describe("galleryHtml", () => {
  const view = galleryView([mobileScenario, webScenario], shots, { git: { revision: "abc1234", dirty: true }, reports: [{ label: "iOS report", href: "reports/ios/report.html" }] });
  const html = galleryHtml(view);

  it("titles the page for every app and stamps the revision", () => {
    expect(html).toContain("<title>Vesta Apps QA</title>");
    expect(html).toContain('data-revision="abc1234"');
    expect(html).toContain("abc1234 · dirty");
  });

  it("renders sections with family and group, and cards with up to three columns", () => {
    expect(html).toContain('data-section-group="Mobile · Home"');
    expect(html).toContain('data-family="web"');
    expect(html).toContain('style="--shots: 3"');
  });

  it("annotates each shot for the shots.json poll and copy references", () => {
    expect(html).toContain('data-screenshot="home.png" data-platform="ios" data-state="captured" data-scenario-id="home"');
    expect(html).toContain('src="shots/ios/home.png?v=1000" data-stamp="1000"');
    expect(html).toContain('data-platform="web-dark" data-state="missing"');
  });

  it("renders a scan row per runner, not per platform", () => {
    expect(html.match(/class="scan-row"/g)).toHaveLength(4);
    expect(html).toContain('data-runner="web"');
    expect(html).not.toContain('data-runner="web-dark"');
  });

  it("links the runner reports it was given and the static assets", () => {
    expect(html).toContain('href="reports/ios/report.html"');
    expect(html).toContain('href="gallery/styles.css"');
    expect(html).toContain('src="gallery/client.js"');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps && npm -w @vesta/visual run test -- view`
Expected: FAIL, module not found.

- [ ] **Step 3: Write `gallery/view.mjs`**

```js
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import { FAMILIES, PLATFORMS, RUNNERS, appsRoot, platformsOfFamily } from "../platforms.mjs";
import { excludedNote, loadAllRegistries, scenarioOnPlatform } from "../registry.mjs";
import { pngSize, shotEntries, storeDirectory } from "../store.mjs";

const execFileAsync = promisify(execFile);
const CARD_COLUMNS = 3;

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export async function gitMetadata() {
  const git = async (args) => {
    try {
      return (await execFileAsync("git", args, { cwd: appsRoot })).stdout.trim();
    } catch {
      return "";
    }
  };
  return {
    revision: (await git(["rev-parse", "--short", "HEAD"])) || "unknown",
    dirty: Boolean(await git(["status", "--porcelain"])),
  };
}

function slotFor(scenario, platform, shots) {
  const { label, frame, theme } = PLATFORMS[platform];
  if (!scenarioOnPlatform(scenario, platform)) {
    return { platform, label, frame, theme, state: "excluded", note: excludedNote(scenario) };
  }
  const entry = (shots[platform] ?? {})[scenario.screenshot];
  if (!entry) return { platform, label, frame, theme, state: "missing", note: "Not captured yet" };
  return { platform, label, frame, theme, state: "captured", src: entry.src, mtime: entry.mtime, size: entry.size ?? null };
}

// The page model: sections keyed by family and group in registry order, mobile first;
// each scenario carries one slot per family platform.
export function galleryView(scenarios, shots, options = {}) {
  const sections = new Map();
  const ordered = Object.keys(FAMILIES).flatMap((family) => scenarios.filter((scenario) => scenario.family === family));
  for (const scenario of ordered) {
    const familyLabel = FAMILIES[scenario.family].label;
    const group = scenario.group || "Other";
    const key = `${familyLabel} · ${group}`;
    const section = sections.get(key) ?? { key, family: scenario.family, familyLabel, group, scenarios: [] };
    section.scenarios.push({
      id: scenario.id,
      title: scenario.title,
      description: scenario.description,
      group,
      screenshot: scenario.screenshot,
      family: scenario.family,
      slots: platformsOfFamily(scenario.family).map((platform) => slotFor(scenario, platform, shots)),
    });
    sections.set(key, section);
  }
  return {
    git: options.git ?? { revision: "unknown", dirty: false },
    reports: options.reports ?? [],
    sections: [...sections.values()],
  };
}

// Frames are gallery chrome around a shot, never baked into the PNG, so the store
// stays diffable. Each frame names its own CSS class in styles.css.
export function frameHtml(frame, screenHtml) {
  if (frame === "browser") {
    return `<span class="frame frame-browser"><span class="browser-bar"><span class="dot"></span><span class="dot"></span><span class="dot"></span><span class="address"></span></span>${screenHtml}</span>`;
  }
  if (frame === "desktop-window") {
    return `<span class="frame frame-desktop-window"><span class="titlebar"><span class="light close"></span><span class="light minimize"></span><span class="light zoom"></span></span>${screenHtml}</span>`;
  }
  if (frame === "phone-browser") {
    return `<span class="frame frame-phone frame-phone-browser"><span class="browser-bar compact"><span class="address"></span></span>${screenHtml}</span>`;
  }
  return `<span class="frame frame-phone">${screenHtml}</span>`;
}

export function slotHtml(scenario, slot) {
  const subject = `${scenario.title} on ${slot.label}`;
  const captured = slot.state === "captured";
  const image = captured ? `${slot.src}?v=${slot.mtime}` : "";
  const screen = `<span class="device-screen"${
    slot.size ? ` style="--shot-ratio: ${slot.size.width} / ${slot.size.height}"` : ""
  }>${
    captured
      ? `<img src="${escapeHtml(image)}" data-stamp="${slot.mtime}" alt="${escapeHtml(subject)}" loading="lazy">`
      : `<span class="missing">${escapeHtml(slot.note)}</span>`
  }</span>`;
  return `
          <div class="shot" data-screenshot="${escapeHtml(scenario.screenshot)}" data-platform="${slot.platform}" data-state="${slot.state}" data-scenario-id="${escapeHtml(scenario.id)}" data-group="${escapeHtml(scenario.group)}" data-title="${escapeHtml(scenario.title)}" data-runner="${PLATFORMS[slot.platform].runner}">
            <button class="preview"${captured ? ` data-image="${escapeHtml(image)}"` : ""} aria-label="Open ${escapeHtml(subject)}">${frameHtml(slot.frame, screen)}</button>
            <div class="shot-meta">
              <span class="platform-tag">${escapeHtml(slot.label)}</span>
              <button class="copy-ref" type="button" aria-label="Copy reference for ${escapeHtml(subject)}">Copy ref</button>
            </div>
          </div>`;
}

export function cardHtml(scenario) {
  const columns = Math.min(scenario.slots.length, CARD_COLUMNS);
  return `
        <article class="card">
          <div class="shots" style="--shots: ${columns}">${scenario.slots.map((slot) => slotHtml(scenario, slot)).join("")}</div>
          <div class="card-copy">
            <div class="card-head">
              <h3>${escapeHtml(scenario.title)}</h3>
              <button class="copy-card" type="button" aria-label="Copy reference for ${escapeHtml(scenario.title)}">Copy ref</button>
            </div>
            <p>${escapeHtml(scenario.description)}</p>
          </div>
        </article>`;
}

export function sectionHtml(section, index) {
  const sectionId = `scenario-section-${index}`;
  const count = section.scenarios.length;
  return `
    <details class="scenario-section" open data-section-group="${escapeHtml(section.key)}" data-family="${section.family}" aria-labelledby="${sectionId}">
      <summary class="section-header">
        <h2 class="section-title" id="${sectionId}">${escapeHtml(section.key)}</h2>
        <span class="section-count">${count} ${count === 1 ? "screen" : "screens"}</span>
        <span class="section-chevron" aria-hidden="true"></span>
      </summary>
      <div class="grid">${section.scenarios.map(cardHtml).join("")}</div>
    </details>`;
}

export function scanRowsHtml() {
  return Object.entries(RUNNERS)
    .map(
      ([runner, definition]) => `
    <div class="scan-row" data-runner="${runner}">
      <span class="scan-runner">${escapeHtml(definition.label)}</span>
      <span class="scan-last">last scan</span>
      <span class="scan-progress"></span>
      <button class="scan-button" type="button">Scan</button>
    </div>`,
    )
    .join("");
}

export async function composeGallery() {
  const registries = await loadAllRegistries();
  const scenarios = Object.values(registries).flatMap((registry) => registry.scenarios);
  const shots = await shotEntries();
  for (const platform of Object.keys(shots)) {
    for (const entry of Object.values(shots[platform])) {
      try {
        entry.size = await pngSize(path.join(storeDirectory, entry.src));
      } catch {
        entry.size = null;
      }
    }
  }
  const reports = Object.entries(RUNNERS)
    .filter(([, definition]) => existsSync(path.join(definition.reportDirectory, "report.html")))
    .map(([runner, definition]) => ({ label: `${definition.label} report`, href: `reports/${runner}/report.html` }));
  return galleryView(scenarios, shots, { git: await gitMetadata(), reports });
}
```

The module graph is one way: `page.mjs` imports from `view.mjs`, never the reverse, so `galleryHtml` lives in `page.mjs` and the test imports it from there.

- [ ] **Step 4: Write `gallery/page.mjs`**

```js
import { escapeHtml, scanRowsHtml, sectionHtml } from "./view.mjs";

// The stylesheet and the client script are static files the server serves under
// /gallery/, so the browser caches both across the 500 ms polls.
export function galleryHtml(view) {
  const sections = view.sections.map(sectionHtml).join("");
  const reportLinks = view.reports
    .map((link) => `<a class="report" href="${escapeHtml(link.href)}">${escapeHtml(link.label)}</a>`)
    .join("\n      ");
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vesta Apps QA</title>
  <link rel="stylesheet" href="gallery/styles.css">
</head>
<body data-revision="${escapeHtml(view.git.revision)}">
  <div class="capture-status" id="capture-status" data-state="ready" role="status" aria-live="polite" hidden>
    <span class="status-spinner" aria-hidden="true"></span>
    <span class="status-copy">
      <strong class="status-title">Capturing screenshots</strong>
      <span class="status-detail">Starting…</span>
    </span>
  </div>
  <header>
    <div>
      <h1>Vesta Apps QA</h1>
    </div>
    <div class="meta">
      <span>${escapeHtml(view.git.revision)}${view.git.dirty ? " · dirty" : ""}</span>
      ${reportLinks}
    </div>
  </header>
  <section class="scan-bar" aria-label="Capture runs">${scanRowsHtml()}
    <label class="gentle-toggle" title="Capture at background priority with fewer workers: slower, but the machine stays responsive.">
      <input type="checkbox" id="gentle-toggle" checked>
      <span>Gentle scans</span>
    </label>
  </section>
  <main>${sections}</main>
  <dialog id="lightbox">
    <button aria-label="Close">×</button>
    <img alt="">
  </dialog>
  <script src="gallery/client.js"></script>
</body>
</html>`;
}
```

- [ ] **Step 5: Write `gallery/styles.css`**

Copy the CSS body from `apps/mobile/scripts/visual-catalog.mjs` lines 1474 to 1848 (everything between `<style>` and `</style>`, without those tags) into `apps/visual/gallery/styles.css`, then apply exactly these edits:

1. Delete the two rules `body[data-platforms="2"] .grid { ... }` and `body[data-platforms="3"] .grid { ... }`. Replace them with:
```css
    .grid {
      grid-template-columns: repeat(auto-fill, minmax(min(100%, 600px), 1fr));
    }
    .scenario-section[data-family="web"] .grid {
      grid-template-columns: repeat(auto-fill, minmax(min(100%, 960px), 1fr));
    }
```
2. Rename `.scan-platform` to `.scan-runner`.
3. Replace the whole `.preview { ... }` rule and its `.preview::before, .preview::after`, `.preview::before`, `.preview::after` rules with:
```css
    .preview {
      display: block;
      width: 100%;
      border: 0;
      padding: 0;
      background: none;
      cursor: zoom-in;
    }
    .frame { position: relative; display: block; width: 100%; }
    .frame-phone {
      border: 1px solid #4b4b55;
      border-radius: 32px;
      padding: 5px;
      background: linear-gradient(145deg, #35353c, #08080b 42%, #222228);
      box-shadow: 0 18px 42px #0008, inset 0 0 0 1px #ffffff14;
    }
    .frame-phone::before, .frame-phone::after {
      content: "";
      position: absolute;
      left: -3px;
      width: 3px;
      border-radius: 2px 0 0 2px;
      background: #34343b;
    }
    .frame-phone::before { top: 18%; height: 9%; }
    .frame-phone::after { top: 30%; height: 14%; }
    .frame-phone .device-screen { --frame-ratio: 603 / 1311; border-radius: 27px; }
    .frame-browser, .frame-desktop-window {
      overflow: hidden;
      border: 1px solid #3a3a42;
      border-radius: 12px;
      background: #1c1c21;
      box-shadow: 0 18px 42px #0008, inset 0 0 0 1px #ffffff10;
    }
    .frame-browser .device-screen { --frame-ratio: 1280 / 800; border-radius: 0; }
    .frame-desktop-window .device-screen { --frame-ratio: 1200 / 750; border-radius: 0; }
    .browser-bar {
      display: flex;
      align-items: center;
      gap: 5px;
      height: 26px;
      padding: 0 10px;
      background: #26262c;
    }
    .browser-bar .dot { width: 8px; height: 8px; border-radius: 50%; background: #4b4b55; }
    .browser-bar .address {
      flex: 1;
      height: 14px;
      margin-left: 8px;
      border-radius: 7px;
      background: #34343b;
    }
    .browser-bar.compact { height: 22px; padding: 0 8px; }
    .browser-bar.compact .address { margin-left: 0; }
    .frame-phone-browser .browser-bar { border-radius: 27px 27px 0 0; }
    .frame-phone-browser .device-screen { --frame-ratio: 420 / 900; border-radius: 0 0 27px 27px; }
    .titlebar {
      position: relative;
      display: flex;
      align-items: center;
      gap: 8px;
      height: 28px;
      padding-left: 12px;
      background: linear-gradient(#2c2c33, #26262c);
    }
    .titlebar .light { width: 12px; height: 12px; border-radius: 50%; }
    .titlebar .close { background: #ff5f57; }
    .titlebar .minimize { background: #febc2e; }
    .titlebar .zoom { background: #28c840; }
```
4. In `.device-screen`, change `aspect-ratio: var(--shot-ratio, 603 / 1311);` to `aspect-ratio: var(--shot-ratio, var(--frame-ratio, 603 / 1311));` and delete its `border-radius: 27px;` line (each frame sets it).
5. In `.capture-status[data-state="error"] .status-spinner`, no change. In `.gentle-toggle`, no change.

- [ ] **Step 6: Write `gallery/client.js`**

Copy the script body from `apps/mobile/scripts/visual-catalog.mjs` lines 1876 to 2119 (everything between `<script>` and `</script>`) into `apps/visual/gallery/client.js`, then apply exactly these edits:

1. In `copyWithFeedback`, the template literal escape `lines.join("\\n")` becomes `lines.join("\n")` (it is a real file now, not a string inside a template).
2. In `showCaptureStatus`: replace `"Recapturing screenshots"` with `"Capturing screenshots"` and `"Running the simulator shards"` with `"Working"`.
3. In the scan button handler: replace
```js
        const platform = button.closest(".scan-row").dataset.platform;
```
with
```js
        const runner = button.closest(".scan-row").dataset.runner;
```
and `"capture/" + platform + "?gentle=" + gentle` with `"capture/" + runner + "?gentle=" + gentle`.
4. Replace the whole `updateScanRows` function with:
```js
    function updateScanRows(payload, status) {
      document.querySelectorAll(".scan-row").forEach((row) => {
        const runner = row.dataset.runner;
        const run = (payload.runs || {})[runner];
        const statusRun = Boolean(
          status && status.state === "capturing" && status.runner === runner && status.startedAt,
        );
        const running = Boolean(run && run.running) || statusRun;
        const button = row.querySelector(".scan-button");
        button.disabled = running;
        button.textContent = running ? "Scanning" : "Scan";
        const slots = document.querySelectorAll(
          '.shot[data-runner="' + runner + '"]:not([data-state="excluded"])',
        );
        // While a scan runs, count this run's replacements from zero; idle, count files on disk.
        const startedMs = running
          ? Date.parse((run && run.startedAt) || (status && status.startedAt) || "")
          : 0;
        let have = 0;
        const mtimes = [];
        slots.forEach((slot) => {
          const entry = (payload[slot.dataset.platform] || {})[slot.dataset.screenshot];
          if (!entry) return;
          mtimes.push(entry.mtime);
          if (!running || entry.mtime >= startedMs) have += 1;
        });
        row.querySelector(".scan-progress").textContent = have + "/" + slots.length;
        const failed = Boolean(run && !running && run.exitCode);
        row.dataset.state = failed ? "failed" : "ok";
        row.querySelector(".scan-last").textContent = failed
          ? "last scan failed, see capture-" + runner + ".log"
          : "last scan " + (mtimes.length ? new Date(Math.max.apply(null, mtimes)).toLocaleString() : "never");
      });
    }
```
5. Replace the whole `markRefreshing` function with:
```js
    function markRefreshing(status, payload) {
      const capturing = Boolean(
        status && status.state === "capturing" && status.runner && status.startedAt,
      );
      const startedMs = capturing ? Date.parse(status.startedAt) : 0;
      document.querySelectorAll(".shot").forEach((shot) => {
        const applies =
          capturing && shot.dataset.runner === status.runner && shot.dataset.state !== "excluded";
        if (!applies) {
          shot.classList.remove("refreshing");
          return;
        }
        const entry = (payload[shot.dataset.platform] || {})[shot.dataset.screenshot];
        shot.classList.toggle("refreshing", !(entry && entry.mtime >= startedMs));
      });
    }
```
6. No other edits. The copied code is plain browser JS; leave its `??` and `?.` operators as they are.

- [ ] **Step 7: Run tests and lint**

Run: `cd apps && npm -w @vesta/visual run test -- view && npm -w @vesta/visual run lint`
Expected: PASS. If lint flags `escapeHtml` or `scanRowsHtml` as unused anywhere, remove the unused import.

- [ ] **Step 8: Commit**

```bash
git add apps/visual/gallery
git commit -m "feat(visual): compose one gallery over every family with per-platform frames"
```

---

### Task 6: The gallery server and CLI

**Files:**
- Create: `apps/visual/gallery/server.mjs`, `apps/visual/cli.mjs`
- Test: `apps/visual/gallery/server.test.mjs`
- Reference: `apps/mobile/scripts/visual-catalog.mjs:2157-2311` (`safeStaticPath`, `serveCatalog`).

**Interfaces:**
- Consumes: `RUNNERS`, `appsRoot`, `visualRoot` (Task 1); `shotEntries`, `storeDirectory` (Task 2); `currentRunStatus` (Task 3); `composeGallery` (Task 5); `galleryHtml` (Task 5, from `page.mjs`).
- Produces: `serveCatalog(port, shouldOpen)`, `spawnCapture(runner, gentle, options)` returning the child, `captureCommand(runner, gentle)` returning `{ command, argumentsList, cwd }`, `safeStaticPath(pathname, baseDirectory)`.
- Routes: `GET /` (composed page), `GET /status.json`, `GET /shots.json` (`{...entries, runs}`), `POST /capture/<runner>?gentle=0|1` (202/409/405), `GET /gallery/<asset>` (styles.css, client.js), `GET /reports/<runner>/<path>` (from `RUNNERS[runner].reportDirectory`), anything else static under the store.

- [ ] **Step 1: Write the failing server tests**

`apps/visual/gallery/server.test.mjs`:
```js
import path from "node:path";
import { describe, expect, it } from "vitest";
import { captureCommand, safeStaticPath } from "./server.mjs";
import { appsRoot } from "../platforms.mjs";

describe("safeStaticPath", () => {
  it("maps a pathname under the base directory and refuses traversal", () => {
    expect(safeStaticPath("/shots/ios/home.png", "/base")).toBe(path.resolve("/base/shots/ios/home.png"));
    expect(safeStaticPath("/../etc/passwd", "/base")).toBeNull();
    expect(safeStaticPath("/", "/base")).toBe(path.resolve("/base/index.html"));
  });
});

describe("captureCommand", () => {
  it("spawns the runner's workspace script from apps/ with its args", () => {
    expect(captureCommand("android-galaxy", false)).toEqual({
      command: "npm",
      argumentsList: ["-w", "@vesta/mobile", "run", "visual:android:capture", "--", "--variant", "android-galaxy"],
      cwd: appsRoot,
    });
  });
  it("appends the runner's own gentle arguments", () => {
    expect(captureCommand("web", true).argumentsList).toEqual(["-w", "@vesta/web", "run", "visual:capture", "--", "--workers=2"]);
    expect(captureCommand("ios", true).argumentsList).toEqual(["-w", "@vesta/mobile", "run", "visual:ios:capture", "--", "--gentle"]);
  });
  it("rejects an unknown runner", () => {
    expect(() => captureCommand("tv", false)).toThrow(/Unknown runner: tv/);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps && npm -w @vesta/visual run test -- server`
Expected: FAIL, module not found.

- [ ] **Step 3: Write `gallery/server.mjs`**

```js
import { spawn } from "node:child_process";
import { closeSync, openSync } from "node:fs";
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { RUNNERS, appsRoot } from "../platforms.mjs";
import { currentRunStatus } from "../run-status.mjs";
import { shotEntries, storeDirectory } from "../store.mjs";
import { galleryHtml } from "./page.mjs";
import { composeGallery } from "./view.mjs";

const galleryDirectory = path.dirname(fileURLToPath(import.meta.url));
const mimeTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
]);

export function safeStaticPath(pathname, baseDirectory) {
  const relative = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
  const target = path.resolve(baseDirectory, relative);
  const relation = path.relative(baseDirectory, target);
  if (relation.startsWith("..") || path.isAbsolute(relation)) return null;
  return target;
}

export function captureCommand(runner, gentle) {
  const definition = RUNNERS[runner];
  if (!definition) throw new Error(`Unknown runner: ${runner}`);
  return {
    command: "npm",
    argumentsList: [
      "-w",
      definition.workspace,
      "run",
      definition.script,
      "--",
      ...definition.args,
      ...(gentle ? definition.gentleArgs : []),
    ],
    cwd: appsRoot,
  };
}

// A capture is its own detached child, logged to the store, so the gallery keeps
// serving while it runs and a crash cannot take the server down.
export function spawnCapture(runner, gentle) {
  const plan = captureCommand(runner, gentle);
  const logFile = openSync(path.join(storeDirectory, `capture-${runner}.log`), "w");
  const child = spawn(plan.command, plan.argumentsList, {
    cwd: plan.cwd,
    env: process.env,
    stdio: ["ignore", logFile, logFile],
  });
  closeSync(logFile);
  return child;
}

async function sendFile(response, target) {
  try {
    const info = await stat(target);
    if (!info.isFile()) throw new Error("Not a file");
    const content = await readFile(target);
    response.writeHead(200, {
      "Content-Type": mimeTypes.get(path.extname(target)) ?? "application/octet-stream",
      "Cache-Control": "no-store",
    });
    response.end(content);
  } catch {
    response.writeHead(404).end("Not found");
  }
}

function sendJson(response, status, payload) {
  response.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  response.end(`${JSON.stringify(payload)}\n`);
}

export async function serveCatalog(port, shouldOpen) {
  const idleRun = { running: false, startedAt: null, finishedAt: null, exitCode: null };
  const captureRuns = Object.fromEntries(Object.keys(RUNNERS).map((runner) => [runner, { ...idleRun }]));
  const startCaptureRun = (runner, gentle) => {
    if (captureRuns[runner].running) return false;
    const child = spawnCapture(runner, gentle);
    captureRuns[runner] = { running: true, startedAt: new Date().toISOString(), finishedAt: null, exitCode: null };
    const finish = (exitCode) => {
      captureRuns[runner] = { ...captureRuns[runner], running: false, finishedAt: new Date().toISOString(), exitCode };
    };
    child.on("error", () => finish(1));
    child.on("exit", (code) => finish(code ?? 1));
    return true;
  };

  const server = createServer(async (request, response) => {
    const url = new URL(request.url ?? "/", "http://localhost");
    const pathname = decodeURIComponent(url.pathname);
    const [, head, second, ...rest] = pathname.split("/");
    if (pathname === "/status.json") {
      sendJson(response, 200, await currentRunStatus());
      return;
    }
    if (pathname === "/shots.json") {
      sendJson(response, 200, { ...(await shotEntries()), runs: captureRuns });
      return;
    }
    if (head === "capture" && RUNNERS[second]) {
      if (request.method !== "POST") {
        response.writeHead(405).end("POST required");
        return;
      }
      const gentle = url.searchParams.get("gentle") !== "0";
      const started = startCaptureRun(second, gentle);
      sendJson(response, started ? 202 : 409, { started, run: captureRuns[second] });
      return;
    }
    if (pathname === "/" || pathname === "/index.html") {
      try {
        const html = galleryHtml(await composeGallery());
        response.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
        response.end(html);
      } catch (error) {
        response.writeHead(500).end(`Could not compose the gallery: ${error.message}`);
      }
      return;
    }
    if (head === "gallery" && ["styles.css", "client.js"].includes(second) && rest.length === 0) {
      await sendFile(response, path.join(galleryDirectory, second));
      return;
    }
    if (head === "reports" && RUNNERS[second]) {
      const target = safeStaticPath(`/${rest.join("/")}`, RUNNERS[second].reportDirectory);
      if (!target) {
        response.writeHead(403).end("Forbidden");
        return;
      }
      await sendFile(response, target);
      return;
    }
    const target = safeStaticPath(pathname, storeDirectory);
    if (!target) {
      response.writeHead(403).end("Forbidden");
      return;
    }
    await sendFile(response, target);
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", resolve);
  });
  const address = `http://127.0.0.1:${port}`;
  console.log(`\nVesta Apps QA: ${address}`);
  if (shouldOpen) {
    spawn(process.platform === "darwin" ? "open" : "xdg-open", [address], { stdio: "ignore" }).on("error", () => {});
  }
  await new Promise((resolve) => {
    const stop = () => server.close(resolve);
    process.once("SIGINT", stop);
    process.once("SIGTERM", stop);
  });
}
```

- [ ] **Step 4: Write `cli.mjs`**

```js
#!/usr/bin/env node
import { mkdir } from "node:fs/promises";
import { RUNNERS } from "./platforms.mjs";
import { storeDirectory } from "./store.mjs";
import { serveCatalog, spawnCapture } from "./gallery/server.mjs";

const DEFAULT_PORT = 4173;

function usage() {
  console.log(`Usage:
  npm run visual                       Serve the gallery and open it
  npm run visual:serve -- [--port N] [--no-open]
  npm run visual:capture -- <runner> [--gentle]

Runners: ${Object.keys(RUNNERS).join(", ")}
`);
}

function parseArguments(values) {
  const [command = "serve", ...rest] = values;
  const options = { command, port: DEFAULT_PORT, open: true, gentle: false, runner: "" };
  for (let index = 0; index < rest.length; index += 1) {
    const argument = rest[index];
    if (argument === "--help") {
      usage();
      process.exit(0);
    }
    if (argument === "--no-open") options.open = false;
    else if (argument === "--gentle") options.gentle = true;
    else if (argument === "--port") {
      const port = Number(rest[index + 1]);
      if (!Number.isInteger(port) || port < 1 || port > 65_535) throw new Error(`Invalid port: ${rest[index + 1]}`);
      options.port = port;
      index += 1;
    } else if (!argument.startsWith("-") && !options.runner) options.runner = argument;
    else throw new Error(`Unknown argument: ${argument}`);
  }
  if (!["serve", "capture"].includes(command)) throw new Error(`Unknown command: ${command}`);
  if (command === "capture" && !RUNNERS[options.runner]) {
    throw new Error(`capture needs a runner: ${Object.keys(RUNNERS).join(", ")}`);
  }
  return options;
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  await mkdir(storeDirectory, { recursive: true });
  if (options.command === "serve") {
    await serveCatalog(options.port, options.open);
    return;
  }
  const child = spawnCapture(options.runner, options.gentle);
  console.log(`Capturing ${options.runner}; log: .visual/capture-${options.runner}.log`);
  const code = await new Promise((resolve) => child.on("exit", (exitCode) => resolve(exitCode ?? 1)));
  process.exitCode = code;
}

main().catch((error) => {
  console.error(`\nVisual QA failed: ${error.message}`);
  process.exitCode = 1;
});
```

- [ ] **Step 5: Run tests and lint**

Run: `cd apps && npm -w @vesta/visual run test && npm -w @vesta/visual run lint`
Expected: PASS (except the `loadRegistry` block of `registry.test.mjs`, which needs Task 8).

- [ ] **Step 6: Smoke the server against the current mobile store**

Run (from `apps/`): `mkdir -p visual/.visual && cp -R mobile/.visual/shots visual/.visual/ && node visual/cli.mjs serve --port 4199 --no-open &` then `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:4199/` and `curl -s http://127.0.0.1:4199/shots.json | head -c 200`, then kill the server.
Expected: the page returns 500 with `Could not compose the gallery` naming the missing `web/visual/scenarios.json` (expected until Task 8); `shots.json` returns 200 with the ios entries. This confirms routing and the store path. Remove the copied `visual/.visual/shots` afterwards (`rm -r visual/.visual/shots`), since Task 7 moves the real one.

- [ ] **Step 7: Commit**

```bash
git add apps/visual/gallery/server.mjs apps/visual/gallery/server.test.mjs apps/visual/cli.mjs
git commit -m "feat(visual): serve the gallery and spawn runner captures from one server"
```

---

### Task 7: Rework the mobile runners onto the shared store

**Files:**
- Create: `apps/mobile/scripts/visual-runner.mjs`, `apps/mobile/scripts/visual-runner.test.mjs`
- Rename: `apps/mobile/scripts/visual-catalog.mjs` -> `visual-ios.mjs`; `visual-catalog.test.mjs` -> `visual-ios.test.mjs`; `visual-catalog-android.mjs` -> `visual-android.mjs`; `visual-catalog-android.test.mjs` -> `visual-android.test.mjs`
- Modify: `apps/mobile/package.json`, `apps/mobile/maestro/visual/capture-screenshot.js`, `apps/mobile/visual/README.md`
- Reference: everything read above from `visual-catalog.mjs` and `visual-catalog-android.mjs`.

**Interfaces:**
- Consumes: `@vesta/visual/platforms` (`PLATFORMS`), `@vesta/visual/store` (`putShot`, `platformShotsDirectory`, `shotDriftWarning`, `atomicWriteFile`), `@vesta/visual/registry` (`loadRegistry`, `scenariosForPlatform`), `@vesta/visual/run-status` (`publishRunStatus`).
- Produces: `visual-runner.mjs` exports `mobileRoot`, `repositoryRoot`, `visualDirectory` (= `apps/mobile/.visual`), `run`, `gentleSpawnPlan`, `setGentleMode`, `activeShardCount`, `exists`, `filesBelow`, `assertHarnessBoundary`, `nativeInputFingerprint`, `jsInputFingerprint`, `jsFingerprintPath`, `jsBundleCurrent`, `recordJsBundle`, `maestroFlowSummary`, `flowFailureError`, `createMaestroFailureParser`, `createInactivityWatchdog`, `writeFileIfChanged`, `fingerprintPaths`, `nativeAnimationHookPath`. `visual-ios.mjs` exports what the Android runner still needs from it: `androidVariants`, `androidVisualDirectory`, `androidWorkDirectory`, `androidMaestroDirectoryOf`, `metroConfigPath` (nothing else the Android runner imports lives in the iOS file after this task).

- [ ] **Step 1: Rename the four files with git**

```bash
cd apps/mobile/scripts
git mv visual-catalog.mjs visual-ios.mjs
git mv visual-catalog.test.mjs visual-ios.test.mjs
git mv visual-catalog-android.mjs visual-android.mjs
git mv visual-catalog-android.test.mjs visual-android.test.mjs
```
Update the import in `visual-android.mjs` (`from "./visual-catalog.mjs"` -> `from "./visual-ios.mjs"`) and in both tests (`./visual-catalog.mjs` -> `./visual-ios.mjs`, `./visual-catalog-android.mjs` -> `./visual-android.mjs`) so the suite still runs. Run `cd apps && npm -w @vesta/mobile run test -- scripts` and confirm it passes before continuing.

- [ ] **Step 2: Extract `visual-runner.mjs` (mobile-shared helpers)**

Create `apps/mobile/scripts/visual-runner.mjs` by moving these blocks verbatim out of `visual-ios.mjs` (each is self-contained; move the imports they need: `spawn`, `createHash`, `access`, `mkdir`, `readFile`, `readdir`, `rename`, `stat`, `writeFile`, `fileURLToPath`, `path`):
- lines 28-31 (`scriptDirectory`, `mobileRoot`, `repositoryRoot`, `visualDirectory`) plus `export` on `mobileRoot`, `repositoryRoot`, `visualDirectory`
- lines 88-91 (`nativeAnimationHookPath`), exported
- lines 96-113 (`shardCount`, gentle mode, `gentleSpawnPlan`)
- lines 290-337 (`run`)
- lines 339-368 (`maestroFlowSummary`, `flowFailureError`)
- lines 370-377 (`exists`)
- lines 389-395 (`writeFileIfChanged`), exported
- lines 397-472 (`fingerprintPaths`, `nativeInputTargets`, `nativeInputFingerprint`, `jsInputTargets`, `jsInputFingerprint`, `jsFingerprintPath`, `jsBundleCurrent`, `recordJsBundle`), with `fingerprintPaths` exported
- lines 1197-1231 (`filesBelow`, `assertHarnessBoundary`)
- lines 2511-2527 (`createInactivityWatchdog`)
- lines 2716-2745 (`ansiEscapePattern`, `createMaestroFailureParser`)

`atomicWriteFile` (lines 379-387) is deleted from mobile: `visual-runner.mjs` imports it from `@vesta/visual/store` and re-exports it (`export { atomicWriteFile } from "@vesta/visual/store";`) for `writeFileIfChanged` and `recordJsBundle`.

In `visual-ios.mjs`, replace the moved blocks with one import:
```js
import {
  activeShardCount,
  assertHarnessBoundary,
  createInactivityWatchdog,
  createMaestroFailureParser,
  exists,
  filesBelow,
  fingerprintPaths,
  flowFailureError,
  gentleSpawnPlan,
  jsBundleCurrent,
  mobileRoot,
  nativeAnimationHookPath,
  nativeInputFingerprint,
  recordJsBundle,
  repositoryRoot,
  run,
  setGentleMode,
  visualDirectory,
  writeFileIfChanged,
} from "./visual-runner.mjs";
```
Drop any name that is then unused (eslint tells you). Note `atomicWriteFile` is imported by `visual-ios.mjs` from `@vesta/visual/store` where still needed.

Move the matching tests out of `visual-ios.test.mjs` into `visual-runner.test.mjs`: the `createInactivityWatchdog`, `maestroFlowSummary`/`flowFailureError`, `gentleSpawnPlan`, and `createMaestroFailureParser` describe blocks (lines 30-87, 122-140, 189-208). Their imports come from `./visual-runner.mjs`.

- [ ] **Step 3: Delete watch mode from `visual-ios.mjs`**

Delete, in `visual-ios.mjs`:
- the `watch as watchPath` import (line 10) and `watchFlowsDirectory` (line 85)
- `CaptureSupersededError` (lines 182-187)
- the `watch` line in `usage()` and the `--gentle only applies` check and `"watch"` in the accepted commands of `parseArguments`
- `syncWatchFlows` (2685-2715), `startContinuousMaestro` (2746-2859), `assignFlowsToShards` (2860-2867), `continuousShardFlow` (2869-2882), `shouldIgnoreWatchPath` (2891-2905), `watchChangePath` (2906-2909), `visualWatchTargets` (2910-2978), `statSyncDirectory` (2979-2982), `watchTargetFingerprints` (2983-2998), `watchCatalog` (2999-3267)
- the `watch` branch in `main()`
- the `cancel(detail)` method of the bridge (lines 2663-2668) and its use of `CaptureSupersededError`

Delete the matching tests from `visual-ios.test.mjs`: the `assignFlowsToShards`, `continuousShardFlow`, `shouldIgnoreWatchPath`, `watchChangePath` describe blocks and their imports.

Rename the bridge env vars: in `runMaestro` (line 1170-1174) `WATCH_CAPTURE_URL=` -> `CAPTURE_URL=`, `WATCH_CAPTURE_URL_1` -> `CAPTURE_URL_1`, `WATCH_CAPTURE_URL_2` -> `CAPTURE_URL_2`. In `apps/mobile/maestro/visual/capture-screenshot.js` rename the same three identifiers (`WATCH_CAPTURE_URL` -> `CAPTURE_URL`, `_1`, `_2`) and the local `watchUrl` -> `directUrl`.

- [ ] **Step 4: Point `visual-ios.mjs` at the shared store, registry, and run status**

In `visual-ios.mjs`:
- Delete `shotsDirectory`, `iosShotsDirectory`, `androidShotsDirectory`, `platformShotsDirectory` (lines 56-58, 66-68), `manifestPath` (86), `scenarioPlatforms`, `scenarioOnPlatform`, `loadManifest` (474-544), `pngSize` (1233-1243), `gitMetadata` (1245-1260), `escapeHtml`, `galleryPlatforms`, `platformLabels`, `shotEntries`, `shotDriftWarning`, `excludedNote`, `galleryView`, `slotHtml`, `galleryHtml`, `composeGallery`, `safeStaticPath`, `serveCatalog` (1262-2311), the `mimeTypes` map (124-130), the run-status block (114-122, 132-180), `runStatusPath`, `STALE_CAPTURING_MS`, and `--no-serve`/`--no-open`/`--port` handling in `usage()`/`parseArguments` (serving is gone; keep `--device`, `--show-simulator`, `--skip-build`, `--clean-native`, `--gentle`, `--help`; the only command is `capture`).
- Add imports:
```js
import { loadRegistry, scenariosForPlatform } from "@vesta/visual/registry";
import { publishRunStatus } from "@vesta/visual/run-status";
import { putShot, shotDriftWarning } from "@vesta/visual/store";
```
- Everywhere `loadManifest()` was called (`prepareCaptureSession`, `runCaptureIteration`), replace with:
```js
  const registry = await loadRegistry("mobile");
  const manifest = { ...registry, scenarios: scenariosForPlatform(registry, "ios") };
```
  (`manifest.appId`, `manifest.flows`, `manifest.scenarios` keep working.)
- In the bridge screenshot handler (lines 2568-2577) replace the temp+rename block with:
```js
      const temporary = path.join(os.tmpdir(), `vesta-visual-${process.pid}-${screenshot}`);
      await run("xcrun", ["simctl", "io", simulator.udid, "screenshot", "--type=png", temporary], { capture: true, quiet: true });
      await putShot("ios", screenshot, temporary);
      await rm(temporary, { force: true });
```
  and delete the `await mkdir(iosShotsDirectory, ...)` in `beginCycle`.
- `reportShotDrift` (2884-2890): the call becomes `shotDriftWarning(seen, manifest.scenarios)` and the log line becomes `` `\nCaptured ${seen.size} iOS screenshots into the visual store.` ``.
- `capture()` (2402-2428): `publishRunStatus("capturing", { message, startedAt, runner: "ios" })`; the final `ready` publish adds `runner: "ios"`; the `error` publish adds `runner: "ios"`; delete the trailing `if (options.serve) await serveCatalog(...)`.
- Delete every export the Android runner no longer needs from `visual-ios.mjs` once Step 5 is done; keep exporting `androidVariants`, `androidVisualDirectory`, `androidWorkDirectory`, `androidMaestroDirectoryOf`, `metroConfigPath`.
- `main()` becomes: parse, `setGentleMode`, `capture(options)`. The failure message stays `Visual catalog failed:` -> change to `iOS visual capture failed:`.
- `usage()` first line: `npm run visual:ios:capture -- [options]`.

Update `visual-ios.test.mjs`: delete the `galleryView`, `galleryHtml`, `shotEntries`, `loadManifest`, `newerRunStatus`, `shotDriftWarning` blocks (moved to `@vesta/visual` in Tasks 2 to 5) and their imports; keep the Metro-fixture blocks (`visual Metro privacy override`, `visual Metro agent fixtures`) untouched.

- [ ] **Step 5: Point `visual-android.mjs` at the shared store, registry, and run status**

In `visual-android.mjs`:
- Replace the import block (lines 20-40) with:
```js
import { loadRegistry, scenariosForPlatform } from "@vesta/visual/registry";
import { publishRunStatus } from "@vesta/visual/run-status";
import { platformShotsDirectory, putShot, shotDriftWarning } from "@vesta/visual/store";
import {
  androidMaestroDirectoryOf,
  androidVariants,
  androidVisualDirectory,
  metroConfigPath,
} from "./visual-ios.mjs";
import {
  assertHarnessBoundary,
  atomicWriteFile,
  exists,
  filesBelow,
  flowFailureError,
  gentleSpawnPlan,
  jsBundleCurrent,
  nativeInputFingerprint,
  recordJsBundle,
  run,
  setGentleMode,
} from "./visual-runner.mjs";
```
  (Delete the local `metroConfigPath` const at line 58; it now comes from `visual-ios.mjs`. Delete `DEFAULT_GALLERY_PORT`, the `serve` command, and `--no-serve`/`--no-open`/`--port` from `usage()`/`parseArguments`; the only command is `capture`.)
- In `stageMaestroShots(sourceDirectory, platform)` (rename the second parameter): replace the `mkdir` + tmp/rename copy loop (lines 640-647) with:
```js
  for (const [name, entry] of newest) {
    await putShot(platform, name, entry.file);
  }
```
  Its callers pass `variant` instead of `platformShotsDirectory(variant)`. `platformShotsDirectory` is then unused in this file; drop it from the import.
- `capture()`: `loadManifest("android")` becomes
```js
  const registry = await loadRegistry("mobile");
  const manifest = { ...registry, scenarios: scenariosForPlatform(registry, variant) };
```
  every `publishRunStatus(..., { ..., platform: variant })` becomes `runner: variant`; `shotDriftWarning(produced, manifest)` becomes `shotDriftWarning(produced, manifest.scenarios)`; the log line becomes `` `\nCaptured ${produced.size} ${androidVariants[variant].label} screenshots into the visual store.` ``; delete the trailing `if (options.serve) ...` block.
- `main()`: only `capture`. Failure message: `Android visual capture failed:`.

Update `visual-android.test.mjs`: the `stageMaestroShots` tests call `stageMaestroShots(source, "android")` and read the result from `platformShotsDirectory("android", base)`. Because `putShot` writes to the real store by default, add a fourth argument to `stageMaestroShots(sourceDirectory, platform, baseDirectory = undefined)` that is passed to `putShot(platform, name, entry.file, baseDirectory)`; the tests pass a tmpdir. `parseArguments` tests: drop the serve/port cases.

- [ ] **Step 6: Update the mobile package scripts**

In `apps/mobile/package.json` replace the seven `visual:*` scripts with:
```json
    "visual:ios:capture": "node ./scripts/visual-ios.mjs capture",
    "visual:android:capture": "node ./scripts/visual-android.mjs capture",
```

- [ ] **Step 7: Move the existing shots into the shared store**

Run (from `apps/`): `mkdir -p visual/.visual && mv mobile/.visual/shots visual/.visual/shots && ls visual/.visual/shots`
Expected: `android android-galaxy ios`.

- [ ] **Step 8: Run the mobile checks and a real iOS capture**

Run: `cd apps && npm -w @vesta/mobile run lint && npm -w @vesta/mobile run check && npm -w @vesta/mobile run test`
Expected: PASS.

Run: `cd apps && npm -w @vesta/mobile run visual:ios:capture -- --gentle`
Expected: the run completes, logs `Captured 49 iOS screenshots into the visual store.`, and `ls visual/.visual/shots/ios | wc -l` is 49 with fresh mtimes. `cat visual/.visual/run-status.json` shows `"runner":"ios"`.

- [ ] **Step 9: Commit**

```bash
git add apps/mobile/scripts apps/mobile/package.json apps/mobile/maestro/visual/capture-screenshot.js
git commit -m "refactor(mobile): capture into the shared visual store and drop watch mode"
```

---

### Task 8: Rework the web runner: JSON registry, six platforms, desktop stub

**Files:**
- Create: `apps/web/visual/scenarios.json`, `apps/web/visual/drives.ts`, `apps/web/visual/registry.test.ts`, `apps/web/visual/harness/native-stub.ts`
- Modify: `apps/web/visual/playwright.config.ts`, `apps/web/visual/capture.spec.ts`, `apps/web/package.json`, `apps/web/vite.config.ts` (test include), `apps/web/tsconfig.node.json` (if `@vesta/visual` types need `allowJs`: they do not, the `.d.mts` files carry types)
- Delete: `apps/web/visual/scenarios.ts`, `apps/web/visual/gallery.mjs`, `apps/web/visual/test-options.ts`, `apps/web/visual/global-setup.ts`

**Interfaces:**
- Consumes: `@vesta/visual/platforms` (`PLATFORMS`), `@vesta/visual/registry` (`loadRegistry`), `@vesta/visual/store` (`putShot`).
- Produces: `DRIVES: Record<string, { drive(page): Promise<void>; settle(page): Promise<void> }>` in `drives.ts`; `installNativeStub(page)` in `harness/native-stub.ts`; a `scenarios.json` whose ids equal `Object.keys(DRIVES)`.

- [ ] **Step 1: Write the failing registry test**

`apps/web/visual/registry.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { loadRegistry } from "@vesta/visual/registry";
import { DRIVES } from "./drives";

describe("web visual registry", () => {
  it("has exactly one drive per registered scenario", async () => {
    const registry = await loadRegistry("web");
    const ids = registry.scenarios.map((scenario) => scenario.id).sort();
    expect(ids).toEqual(Object.keys(DRIVES).sort());
  });

  it("carries a title, description, and group for every card", async () => {
    const registry = await loadRegistry("web");
    for (const scenario of registry.scenarios) {
      expect(scenario.title.length).toBeGreaterThan(0);
      expect(scenario.description.length).toBeGreaterThan(0);
      expect(["Onboarding", "Agent settings"]).toContain(scenario.group);
    }
  });
});
```
Add `"visual/*.test.ts"` next to `"visual/harness/*.test.ts"` in the vitest `include` at `apps/web/vite.config.ts:110`.

- [ ] **Step 2: Run to verify failure**

Run: `cd apps && npm -w @vesta/web run test -- visual/registry`
Expected: FAIL, `./drives` not found.

- [ ] **Step 3: Write `scenarios.json`**

Every entry below maps one to one onto the existing `scenarios.ts` entry of the same id (state fields copied; `deltas` are named by a string the spec resolves, since JSON cannot hold a built frame). Create `apps/web/visual/scenarios.json`:
```json
{
  "version": 1,
  "scenarios": [
    { "id": "name-empty", "title": "Name step, empty", "description": "The first onboarding step before any name is typed; continue is disabled.", "group": "Onboarding" },
    { "id": "name-valid", "title": "Name step, valid", "description": "A valid agent name typed; continue is enabled.", "group": "Onboarding" },
    { "id": "name-rejected", "title": "Name rejected", "description": "The gateway refused the name as taken and the flow bounced back to the name step.", "group": "Onboarding", "createResponse": { "status": 409, "body": { "error": "name already taken" } } },
    { "id": "provider-choice", "title": "Provider choice", "description": "The provider picker with every provider the manifest offers.", "group": "Onboarding" },
    { "id": "provider-key-entry", "title": "Provider key entry", "description": "The subscription key field for a key-backed provider (Z.AI).", "group": "Onboarding" },
    { "id": "provider-oauth", "title": "Claude sign-in", "description": "The Claude OAuth step with the paste-code field.", "group": "Onboarding" },
    { "id": "provider-oauth-openai", "title": "ChatGPT sign-in", "description": "The ChatGPT device-code step showing the code to enter.", "group": "Onboarding" },
    { "id": "provider-key-kimi", "title": "Kimi key entry", "description": "The subscription key field for Kimi Code.", "group": "Onboarding" },
    { "id": "provider-model", "title": "Model picker, OpenRouter", "description": "The live OpenRouter model list after a key is accepted.", "group": "Onboarding" },
    { "id": "provider-model-loading", "title": "Model picker, loading", "description": "The model list skeleton while the OpenRouter catalog is still loading.", "group": "Onboarding", "hang": "openrouter-models" },
    { "id": "provider-model-claude", "title": "Model picker, Claude expanded", "description": "The Claude picker with the floating aliases and the expanded live list.", "group": "Onboarding" },
    { "id": "provider-model-claude-collapsed", "title": "Model picker, Claude collapsed", "description": "The Claude picker showing only the aliases with the live list collapsed.", "group": "Onboarding" },
    { "id": "provider-model-zai", "title": "Model picker, Z.AI", "description": "The fixed Z.AI catalog.", "group": "Onboarding" },
    { "id": "provider-model-kimi", "title": "Model picker, Kimi", "description": "The fixed Kimi Code catalog.", "group": "Onboarding" },
    { "id": "provider-model-openai", "title": "Model picker, ChatGPT", "description": "The fixed ChatGPT catalog after the device-code step.", "group": "Onboarding" },
    { "id": "personality-default", "title": "Personality, default", "description": "The vibe picker with the default personality pressed.", "group": "Onboarding" },
    { "id": "personality-selected", "title": "Personality, selected", "description": "The vibe picker after choosing a different personality.", "group": "Onboarding" },
    { "id": "creating-pulling", "title": "Creating, pulling image", "description": "The creation progress while the agent image downloads.", "group": "Onboarding", "deltas": ["pulling"] },
    { "id": "creating-starting", "title": "Creating, starting", "description": "The creation progress while the container starts.", "group": "Onboarding", "deltas": ["starting"] },
    { "id": "creating-failed", "title": "Creation failed", "description": "The gateway failed the create call and the flow offers a retry.", "group": "Onboarding", "createResponse": { "status": 500, "body": { "error": "gateway ran out of disk" } } },
    { "id": "done", "title": "Agent ready", "description": "Onboarding complete: the new agent is alive and the say-hi action shows.", "group": "Onboarding", "agentStatus": "alive" },
    { "id": "settings-model-zai", "title": "Change model, Z.AI", "description": "The settings change-model dialog for a Z.AI agent.", "group": "Agent settings", "route": "/agent/luna/settings", "agentName": "luna", "provider": { "kind": "zai", "model": "glm-5.2", "resolved_model": "glm-5.2", "max_context_tokens": 131072, "authed": true, "plan": null } },
    { "id": "settings-model-kimi", "title": "Change model, Kimi", "description": "The settings change-model dialog for a Kimi Code agent.", "group": "Agent settings", "route": "/agent/luna/settings", "agentName": "luna", "provider": { "kind": "kimi", "model": "kimi-for-coding", "resolved_model": "kimi-for-coding", "max_context_tokens": 131072, "authed": true, "plan": null } },
    { "id": "settings-model-openai", "title": "Change model, ChatGPT", "description": "The settings change-model dialog for a ChatGPT agent.", "group": "Agent settings", "route": "/agent/luna/settings", "agentName": "luna", "provider": { "kind": "openai", "model": "gpt-5.6-sol", "resolved_model": "gpt-5.6-sol", "max_context_tokens": 131072, "authed": true, "plan": null } }
  ]
}
```
Defaults the spec applies when a field is absent: `agentStatus: "starting"`, `createResponse: null`, `deltas: []`, `route: "/new"`.

- [ ] **Step 4: Write `drives.ts`**

Move the closures from `scenarios.ts` into a map. Create `apps/web/visual/drives.ts`:
```ts
import { expect, type Page } from "@playwright/test";
import { AGENT } from "./harness/http-fixtures";

export interface Drive {
  drive: (page: Page) => Promise<void>;
  settle: (page: Page) => Promise<void>;
}

async function fillName(page: Page, name: string): Promise<void> {
  await page.getByPlaceholder("name your agent").fill(name);
}
async function submitName(page: Page): Promise<void> {
  await page.getByRole("button", { name: "continue" }).click();
}
async function crossProvider(page: Page): Promise<void> {
  await page.getByText("Z.AI", { exact: true }).click();
  await page.getByPlaceholder("Z.AI subscription key").fill("visual-zai-key");
  await page.getByRole("button", { name: "next" }).click();
  // Z.AI shows its fixed model catalog in onboarding; take the default.
  await page.getByRole("button", { name: "continue" }).click();
}
async function toCreating(page: Page): Promise<void> {
  await fillName(page, AGENT);
  await submitName(page);
  await crossProvider(page);
  await expect(page.getByText("pick a vibe")).toBeVisible();
  await page.getByRole("button", { name: "continue" }).click();
}
async function toProvider(page: Page, provider: string): Promise<void> {
  await fillName(page, AGENT);
  await submitName(page);
  await page.getByText(provider, { exact: true }).click();
}
async function toKeyedModel(page: Page, provider: string, placeholder: string, key: string): Promise<void> {
  await toProvider(page, provider);
  await page.getByPlaceholder(placeholder).fill(key);
  await page.getByRole("button", { name: "next" }).click();
}
async function toClaudeModel(page: Page): Promise<void> {
  await toProvider(page, "Claude");
  await page.getByPlaceholder("paste code here").fill("visual-code");
  await page.getByRole("button", { name: "continue" }).click();
}
function settingsModel(visibleLabel: string): Drive {
  return {
    drive: async (page) => {
      await page.getByRole("button", { name: "change model" }).click();
    },
    settle: async (page) => {
      await expect(page.getByText(visibleLabel)).toBeVisible();
    },
  };
}

export const DRIVES: Record<string, Drive> = {
  "name-empty": {
    drive: () => Promise.resolve(),
    settle: async (page) => {
      await expect(page.getByPlaceholder("name your agent")).toBeVisible();
      await expect(page.getByRole("button", { name: "continue" })).toBeDisabled();
    },
  },
  "name-valid": {
    drive: (page) => fillName(page, "luna"),
    settle: async (page) => {
      await expect(page.getByRole("button", { name: "continue" })).toBeEnabled();
    },
  },
  "name-rejected": {
    drive: toCreating,
    settle: async (page) => {
      await expect(page.getByText("name already taken")).toBeVisible();
      await expect(page.getByPlaceholder("name your agent")).toBeVisible();
    },
  },
  "provider-choice": {
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
    },
    settle: async (page) => {
      await expect(page.getByText("Z.AI", { exact: true })).toBeVisible();
      await expect(page.getByText("OpenRouter", { exact: true })).toBeVisible();
    },
  },
  "provider-key-entry": {
    drive: (page) => toProvider(page, "Z.AI"),
    settle: async (page) => {
      await expect(page.getByPlaceholder("Z.AI subscription key")).toBeVisible();
    },
  },
  "provider-oauth": {
    drive: (page) => toProvider(page, "Claude"),
    settle: async (page) => {
      await expect(page.getByText("sign in to claude")).toBeVisible();
      await expect(page.getByPlaceholder("paste code here")).toBeVisible();
    },
  },
  "provider-oauth-openai": {
    drive: (page) => toProvider(page, "ChatGPT"),
    settle: async (page) => {
      await expect(page.getByText("sign in to ChatGPT")).toBeVisible();
      await expect(page.getByText("WDJB-MJHT")).toBeVisible();
    },
  },
  "provider-key-kimi": {
    drive: (page) => toProvider(page, "Kimi Code"),
    settle: async (page) => {
      await expect(page.getByPlaceholder("Kimi Code subscription key")).toBeVisible();
    },
  },
  "provider-model": {
    drive: (page) => toKeyedModel(page, "OpenRouter", "sk-or-v1-...", "sk-or-v1-visual"),
    settle: async (page) => {
      await expect(page.getByText("pick a model")).toBeVisible();
      await expect(page.getByText("Claude Sonnet 5")).toBeVisible();
    },
  },
  "provider-model-loading": {
    drive: (page) => toKeyedModel(page, "OpenRouter", "sk-or-v1-...", "sk-or-v1-visual"),
    settle: async (page) => {
      await expect(page.locator('[data-slot="skeleton"]').first()).toBeVisible();
    },
  },
  "provider-model-claude": {
    drive: async (page) => {
      await toClaudeModel(page);
      await page.getByRole("button", { name: "more models" }).click();
    },
    settle: async (page) => {
      await expect(page.getByRole("button", { name: "Opus", exact: true })).toBeVisible();
      await expect(page.getByText("Claude Opus 5")).toBeVisible();
    },
  },
  "provider-model-claude-collapsed": {
    drive: toClaudeModel,
    settle: async (page) => {
      await expect(page.getByRole("button", { name: "more models" })).toBeVisible();
      await expect(page.getByText("Claude Opus 5")).toBeHidden();
    },
  },
  "provider-model-zai": {
    drive: (page) => toKeyedModel(page, "Z.AI", "Z.AI subscription key", "visual-zai-key"),
    settle: async (page) => {
      await expect(page.getByText("pick a model")).toBeVisible();
      await expect(page.getByText("GLM 5 Turbo")).toBeVisible();
    },
  },
  "provider-model-kimi": {
    drive: (page) => toKeyedModel(page, "Kimi Code", "Kimi Code subscription key", "visual-kimi-key"),
    settle: async (page) => {
      await expect(page.getByText("pick a model")).toBeVisible();
      await expect(page.getByText("Coding Highspeed")).toBeVisible();
    },
  },
  "provider-model-openai": {
    drive: async (page) => {
      await toProvider(page, "ChatGPT");
      await page.getByRole("button", { name: "continue" }).click();
    },
    settle: async (page) => {
      await expect(page.getByText("pick a model")).toBeVisible();
      await expect(page.getByText("GPT 5.6 Terra")).toBeVisible();
    },
  },
  "personality-default": {
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await crossProvider(page);
      await expect(page.getByText("pick a vibe")).toBeVisible();
    },
    settle: async (page) => {
      await expect(page.getByRole("button", { name: /dry/ })).toHaveAttribute("aria-pressed", "true");
    },
  },
  "personality-selected": {
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await crossProvider(page);
      await page.getByRole("button", { name: /chill/ }).click();
    },
    settle: async (page) => {
      await expect(page.getByRole("button", { name: /chill/ })).toHaveAttribute("aria-pressed", "true");
    },
  },
  "creating-pulling": {
    drive: toCreating,
    settle: async (page) => {
      await expect(page.getByText("downloading the agent image...")).toBeVisible();
    },
  },
  "creating-starting": {
    drive: toCreating,
    settle: async (page) => {
      await expect(page.getByText("starting up...")).toBeVisible();
    },
  },
  "creating-failed": {
    drive: toCreating,
    settle: async (page) => {
      await expect(page.getByText("gateway ran out of disk")).toBeVisible();
      await expect(page.getByRole("button", { name: "try again" })).toBeVisible();
    },
  },
  done: {
    drive: toCreating,
    settle: async (page) => {
      await expect(page.getByText(`${AGENT} is ready`)).toBeVisible();
      await expect(page.getByRole("button", { name: "say hi" })).toBeVisible();
    },
  },
  "settings-model-zai": settingsModel("GLM 5 Turbo"),
  "settings-model-kimi": settingsModel("Coding Highspeed"),
  "settings-model-openai": settingsModel("GPT 5.6 Terra"),
};
```
Delete `apps/web/visual/scenarios.ts`.

- [ ] **Step 5: Run the registry test**

Run: `cd apps && npm -w @vesta/web run test -- visual/registry`
Expected: PASS. Also run `npm -w @vesta/visual run test` now: the `loadRegistry and loadAllRegistries` block passes. If it reports a cross-family collision (an id or screenshot present in both registries), rename the **web** id in `scenarios.json` and `drives.ts` (prefix it with `web-`) and re-run.

- [ ] **Step 6: Write the native stub**

`apps/web/visual/harness/native-stub.ts`:
```ts
import type { Page } from "@playwright/test";

// Defines window.vestaNative before app code runs, so the app takes its real
// desktop path (.desktop, .vibrancy, data-platform="macos", titlebar inset).
// Every method is inert or memory-backed; the contract is VestaNativeApi in
// apps/web/src/lib/native/types.ts.
export async function installNativeStub(page: Page): Promise<void> {
  await page.addInitScript(() => {
    let stored: unknown = null;
    const noop = (): void => undefined;
    const resolved = (): Promise<void> => Promise.resolve();
    window.vestaNative = {
      platform: "darwin",
      focusWindow: resolved,
      setTheme: noop,
      openExternal: resolved,
      storeRead: () => Promise.resolve(stored),
      storeWrite: (value: unknown) => {
        stored = value;
        return Promise.resolve();
      },
      storeClear: () => {
        stored = null;
        return Promise.resolve();
      },
      oauthStart: () => Promise.resolve(0),
      onOauthCallback: () => noop,
      oauthCancel: resolved,
      onWindowFocus: () => noop,
      windowMinimize: resolved,
      windowToggleMaximize: resolved,
      windowClose: resolved,
      windowIsMaximized: () => Promise.resolve(false),
      onWindowMaximizedChange: () => noop,
    };
  });
}
```
`window.vestaNative` is declared globally by `apps/web/src/lib/native/types.ts`; the harness compiles in the node tsconfig project which does not include `src/`, so add a local declaration at the top of `native-stub.ts`, above the import:
```ts
declare global {
  interface Window {
    vestaNative?: {
      platform: string;
      focusWindow(): Promise<void>;
      setTheme(theme: "light" | "dark"): void;
      openExternal(url: string): Promise<void>;
      storeRead(): Promise<unknown>;
      storeWrite(value: unknown): Promise<void>;
      storeClear(): Promise<void>;
      oauthStart(): Promise<number>;
      onOauthCallback(cb: (url: string) => void): () => void;
      oauthCancel(port: number): Promise<void>;
      onWindowFocus(cb: (focused: boolean) => void): () => void;
      windowMinimize(): Promise<void>;
      windowToggleMaximize(): Promise<void>;
      windowClose(): Promise<void>;
      windowIsMaximized(): Promise<boolean>;
      onWindowMaximizedChange(cb: (maximized: boolean) => void): () => void;
    };
  }
}
export {};
```
(Place it after the `import type { Page }` line; the trailing `export {}` is not needed since the file already has an export.)

- [ ] **Step 7: Rewrite `playwright.config.ts`**

```ts
import { defineConfig } from "@playwright/test";
import { PLATFORMS } from "@vesta/visual/platforms";

const WEB = { width: 1280, height: 800 };
const DESKTOP = { width: 1200, height: 750 };
const NARROW = { width: 420, height: 900 };
const VIEWPORTS: Record<string, { width: number; height: number }> = {
  browser: WEB,
  "desktop-window": DESKTOP,
  "phone-browser": NARROW,
};

// One project per web-family platform, named by its platform id, so the spec
// writes each shot straight into the store under that id.
const projects = Object.entries(PLATFORMS)
  .filter(([, platform]) => platform.family === "web")
  .map(([name, platform]) => ({
    name,
    use: { viewport: VIEWPORTS[platform.frame] ?? WEB, colorScheme: platform.theme },
  }));

export default defineConfig({
  testDir: ".",
  testMatch: "capture.spec.ts",
  outputDir: "../.visual/artifacts",
  reporter: [["list"], ["html", { outputFolder: "../.visual/report", open: "never" }]],
  timeout: 60000,
  fullyParallel: true,
  // 12-core host; 8 keeps headroom. A gentle scan passes --workers=2.
  workers: 8,
  webServer: {
    command: "npm run dev",
    cwd: "..",
    url: "http://localhost:1430",
    reuseExistingServer: true,
    timeout: 60000,
    env: { HTTPS: "false" },
  },
  use: {
    baseURL: "http://localhost:1430",
    contextOptions: { reducedMotion: "reduce" },
  },
  projects,
});
```

- [ ] **Step 8: Rewrite `capture.spec.ts`**

```ts
import { test } from "@playwright/test";
import type { AgentStatus } from "@vesta/core";
import { PLATFORMS } from "@vesta/visual/platforms";
import { loadRegistry } from "@vesta/visual/registry";
import { putShot } from "@vesta/visual/store";
import { DRIVES } from "./drives";
import { installGatewayMocks, type HangEndpoint, type ProviderInfoFixture } from "./harness/http-fixtures";
import { installNativeStub } from "./harness/native-stub";
import { seedStorage } from "./harness/storage";
import { agentDelta, aliveAgentNode, installSyncSocket, startingAgent } from "./harness/sync-fixtures";
import { AGENT } from "./harness/http-fixtures";

// The registry carries the card data plus the JSON-serialisable state; the
// closures live in drives.ts. Typed here, at the boundary.
interface WebScenario {
  id: string;
  route?: string;
  agentStatus?: AgentStatus;
  createResponse?: { status: number; body: { error: string } } | null;
  deltas?: ("pulling" | "starting")[];
  hang?: HangEndpoint;
  agentName?: string;
  provider?: ProviderInfoFixture;
}

const registry = await loadRegistry("web");

// The context runs with reducedMotion: "reduce", which the app treats as "no
// animation at all", so a single screenshot after the settle assertion is the final frame.
for (const scenario of registry.scenarios as unknown as WebScenario[]) {
  test(scenario.id, async ({ page }, testInfo) => {
    const platform = PLATFORMS[testInfo.project.name as keyof typeof PLATFORMS];
    if (platform.frame === "desktop-window") await installNativeStub(page);
    await seedStorage(page, platform.theme);
    await installSyncSocket(
      page,
      (scenario.deltas ?? []).map((phase) => agentDelta(AGENT, startingAgent(phase))),
      scenario.agentName ? { [scenario.agentName]: aliveAgentNode() } : {},
    );
    await installGatewayMocks(page, {
      agentStatus: scenario.agentStatus ?? "starting",
      createResponse: scenario.createResponse ?? null,
      hang: scenario.hang,
      provider: scenario.provider,
    });
    await page.goto(scenario.route ?? "/new");
    const { drive, settle } = DRIVES[scenario.id];
    await drive(page);
    await settle(page);
    // Park the pointer so no card renders its hover state in the shot.
    await page.mouse.move(0, 0);
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    const shot = testInfo.outputPath(`${scenario.id}.png`);
    await page.screenshot({ path: shot, animations: "disabled", caret: "hide" });
    await putShot(testInfo.project.name, `${scenario.id}.png`, shot);
  });
}
```
Fix the duplicate `AGENT` import by merging it into the first `http-fixtures` import line. If `startingAgent`'s parameter type is narrower than `"pulling" | "starting"`, match `deltas` to its `BuildPhase` type: `import type { BuildPhase } from "@vesta/core";` and `deltas?: BuildPhase[]`.

Delete `apps/web/visual/test-options.ts`, `apps/web/visual/global-setup.ts`, and `apps/web/visual/gallery.mjs`.

- [ ] **Step 9: Update the web package scripts**

In `apps/web/package.json` replace the two `visual*` scripts with one:
```json
    "visual:capture": "playwright test --config visual/playwright.config.ts",
```

- [ ] **Step 10: Run the web checks and a real web capture**

Run: `cd apps && npm -w @vesta/web run lint && npm -w @vesta/web run check && npm -w @vesta/web run test`
Expected: PASS. If `tsc` cannot resolve `@vesta/visual/*` types, confirm `apps/visual/package.json` `exports` carry the `types` condition and that `apps/web/tsconfig.node.json` uses `"moduleResolution": "bundler"` (or `node16`/`nodenext`); both honour `exports`.

Run: `npx playwright install chromium` once if chromium is absent, then `cd apps && npm -w @vesta/web run visual:capture`
Expected: 24 scenarios x 6 projects = 144 tests pass; `ls visual/.visual/shots/ | sort` lists all nine platform dirs, and `ls visual/.visual/shots/desktop-dark | wc -l` is 24. Open one `desktop` shot and confirm the title-bar inset (content starts below the traffic-light zone) and one `web-dark` shot renders dark.

- [ ] **Step 11: Commit**

```bash
git add apps/web/visual apps/web/package.json apps/web/vite.config.ts
git commit -m "feat(web): capture six web platforms into the shared visual store"
```

---

### Task 9: Wire the umbrella: scripts, check.sh, CI

**Files:**
- Modify: `apps/package.json`, `check.sh`, `.github/workflows/ci.yml`

- [ ] **Step 1: Replace the visual scripts in `apps/package.json`**

Replace the nine `mobile:visual*` and `web:visual*` lines with:
```json
    "mobile:visual:capture": "npm -w @vesta/mobile run visual:ios:capture --",
    "mobile:visual:android:capture": "npm -w @vesta/mobile run visual:android:capture --",
    "web:visual:capture": "npm -w @vesta/web run visual:capture --",
    "visual": "npm -w @vesta/visual run serve",
    "visual:serve": "npm -w @vesta/visual run serve -- --no-open",
    "visual:capture": "npm -w @vesta/visual run capture --"
```

- [ ] **Step 2: Add `app-visual` to `check.sh`**

After `check_app_desktop()` add:
```bash
check_app_visual() {
  (
    cd apps
    if [ ! -d node_modules ]; then
      npm install
    fi
    npm -w @vesta/visual run lint
    npm -w @vesta/visual run test
  )
}
```
In `check_web()` add `check_app_visual` after `check_app_desktop`. In the dispatch `case` add `app-visual) check_app_visual ;;` after `app-desktop)`. In the usage text add after the `app-desktop` line:
```
  app-visual     @vesta/visual: eslint + vitest (the shared visual QA gallery and store)
```
and change the `web` line to `all five app slices below (core, web, desktop, visual, mobile); CI runs them as separate jobs`.

- [ ] **Step 3: Add the CI job**

In `.github/workflows/ci.yml`:
- In `detect-changes` outputs add `visual: ${{ steps.filter.outputs.visual }}` next to the other app outputs, and in the paths filter add:
```yaml
            visual:
              - 'apps/visual/**'
              - 'apps/mobile/visual/scenarios.json'
              - 'apps/web/visual/scenarios.json'
              - 'apps/package.json'
              - 'apps/package-lock.json'
              - '.github/workflows/ci.yml'
              - 'check.sh'
```
- Add `'apps/visual/**'` to the `web` and `mobile` filter lists (their runners import it).
- After `test-app-desktop` add:
```yaml
  test-app-visual:
    name: Apps · visual
    needs: detect-changes
    if: >-
      github.event_name != 'pull_request' ||
      needs.detect-changes.outputs.visual == 'true'
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7

      - name: Setup Node
        uses: actions/setup-node@v7
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: apps/package-lock.json

      - name: Install deps
        run: npm --prefix apps ci

      - name: Run visual checks
        run: ./check.sh app-visual
```
- Add `- test-app-visual` to the `merge-gate-ci` needs list (near line 1084).

- [ ] **Step 4: Run the slices locally**

Run: `./check.sh app-visual && ./check.sh app-web && ./check.sh app-mobile`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add apps/package.json check.sh .github/workflows/ci.yml
git commit -m "chore(visual): wire @vesta/visual into scripts, check.sh, and CI"
```

---

### Task 10: Docs and the skill

**Files:**
- Create: `apps/visual/README.md`, `apps/visual/.agents/skills/visual-qa/SKILL.md`, `apps/visual/.agents/skills/visual-qa/agents/openai.yaml`, `.claude/skills/visual-qa/SKILL.md`
- Modify: `apps/mobile/visual/README.md`, `apps/web/visual/README.md`, `.claude/workflows/product-critique.js`
- Delete: `apps/mobile/.agents/skills/mobile-visual-qa/`, `.claude/skills/mobile-visual-qa/`
- Reference: `apps/mobile/.agents/skills/mobile-visual-qa/SKILL.md` (330 lines), `apps/mobile/visual/README.md` (716 lines), `apps/web/visual/README.md` (31 lines).

- [ ] **Step 1: Write `apps/visual/README.md`**

Write it fresh in Simplified Technical English (short sentences, one instruction each). Sections and required content:
1. **Title**: `# Vesta visual QA`. One paragraph: one deterministic screenshot system covers every Vesta client; one gallery shows every scenario on every platform; local only, no CI capture.
2. **Quick start** (from `apps/`): `npm run visual` (serve + open on http://127.0.0.1:4173), `npm run visual:capture -- ios|android|android-galaxy|web [--gentle]`, the runner-level `npm run mobile:visual:capture -- --device "iPhone 17"`, `npm run mobile:visual:android:capture -- --variant android-galaxy`, `npm run web:visual:capture -- --project web-dark`; `npx playwright install chromium` once for the web runner. Say that recapture is Scan in the gallery; there is no watch mode.
3. **Platforms**: a table of the nine ids with label, family, theme, frame, runner (copy from `platforms.mjs`). Say a theme variant is its own platform, like `android-galaxy`.
4. **Architecture**: the data path (each app's runner -> `putShot` -> `apps/visual/.visual/shots/<platform>/<id>.png` -> gallery composes both registries plus the store per request), and the ownership table: `apps/visual/platforms.mjs`, `registry.mjs`, `store.mjs`, `run-status.mjs`, `gallery/`, `apps/mobile/visual/` + `apps/mobile/scripts/visual-*.mjs`, `apps/web/visual/`.
5. **Registry contract**: the JSON shape, `screenshot` default, `platforms` restriction, cross-family uniqueness, mobile `flows`/`appId`, web state fields.
6. **Production boundary**: the forbidden list from the mobile README lines 104-120, worded for every app (`app/`, `src/`, checked-in native code; no capture flags, no bot-only test ids, no fake screens; frames are gallery CSS).
7. **Gallery**: sections `<Family> · <Group>`, cards, slots and frames, Scan rows per runner, gentle mode (`--gentle` on Maestro runners, `--workers=2` on web), copy-ref format, `/reports/<runner>/report.html`.
8. **Add a scenario**: mobile (flow step + `takeScreenshot` + bridge callback + `scenarios.json` entry) and web (`scenarios.json` entry + `drives.ts` entry + fixtures), then run the runner and inspect the gallery.
9. **Troubleshooting**: the mobile list from README lines 635-706 condensed to one line each, plus web items: missing chromium, port 1430 busy, a `settle` failing.
Keep it under 250 lines.

- [ ] **Step 2: Shrink the two runner READMEs**

`apps/mobile/visual/README.md`: keep only what is mobile-runner-specific: simulators/emulators, the isolated native build and its cache, `--device`, `--variant`, `--show-simulator`, `--clean-native`, the Metro fixture substitution, and the Maestro flow conventions (sections "How a capture runs", "Why scenario groups use separate launches", "Android catalog", "Selector and scenario guidelines", "Troubleshooting" mobile items). Delete "Quick start" commands that serve, "Watch-mode behavior", "Using the gallery", and every mention of ports 4173/4174 and `visual:serve`/`visual:watch`. Start with one line: `Runner details for the mobile family. The system, gallery, and registry contract are documented in ../../visual/README.md.` Target under 300 lines.

`apps/web/visual/README.md`: rewrite to: the one-line pointer above; how determinism is injected (storage seed, `/sync` route, HTTP routes); the six projects and what `desktop*` adds (`installNativeStub`); commands (`npm run web:visual:capture -- --project desktop-dark`); `npx playwright install chromium`; the boundary rule; adding a scenario (`scenarios.json` + `drives.ts`, keep `fixtures.test.ts` and `registry.test.ts` green). Under 60 lines.

- [ ] **Step 3: Move and rename the skill**

```bash
git mv apps/mobile/.agents/skills/mobile-visual-qa apps/visual/.agents/skills/visual-qa
git rm -r .claude/skills/mobile-visual-qa
mkdir -p .claude/skills/visual-qa
```
Edit `apps/visual/.agents/skills/visual-qa/SKILL.md`: frontmatter `name: visual-qa`, description: `Operate and extend Vesta's deterministic visual QA system for every app: capture or serve the gallery, add or update scenarios for mobile (Maestro) or web and desktop (Playwright), create visual-only fixtures, diagnose captures, and review changes against the production boundary.` Rewrite the body against the new README: "Work from `apps/`"; read `apps/visual/README.md`, both `scenarios.json`, the runner READMEs, `platforms.mjs`; the ownership table lists the new paths; "Run the system" lists the new commands; delete every watch-mode step; "Add a screenshot state" gets a web branch (JSON entry + `drives.ts` + fixture); "Diagnose failures" adds `apps/visual/.visual/capture-<runner>.log` and `apps/web/.visual/report/`. Keep it under 300 lines.

Edit `apps/visual/.agents/skills/visual-qa/agents/openai.yaml`:
```yaml
display_name: "Visual QA"
short_description: "Capture and extend the deterministic Vesta apps gallery"
default_prompt: "Use $visual-qa to add or debug deterministic screenshots in the Vesta visual QA harness (mobile, web, desktop)."
```

Write `.claude/skills/visual-qa/SKILL.md`:
```markdown
---
name: visual-qa
description: Operate and extend Vesta's deterministic visual QA system for every app (mobile, web, desktop). Use when capturing or serving the gallery, adding screenshot scenarios or fixtures, debugging captures, or reviewing the production boundary.
---

# Visual QA

Read `../../../apps/visual/.agents/skills/visual-qa/SKILL.md` completely
before taking action, then follow it as the canonical visual QA skill.

Keep the canonical skill under `apps/visual/.agents/skills/visual-qa/` as the
single source of truth. Update it instead of duplicating instructions here so
both agent systems remain aligned.
```

- [ ] **Step 4: Repoint the product-critique workflow**

In `.claude/workflows/product-critique.js` line 6, replace `tools/critique/capture-ui.mjs` with `npm run visual:capture -- <runner> (see apps/visual/README.md)`. Grep the repo for `mobile-visual-qa` and `capture-ui.mjs`; both must return no hits.

- [ ] **Step 5: Verify prose rules and commit**

Run: `rg -n " - | — " apps/visual/README.md apps/visual/.agents/skills/visual-qa/SKILL.md apps/mobile/visual/README.md apps/web/visual/README.md .claude/skills/visual-qa/SKILL.md` and remove any dash used as a separator in prose (table cells and code are fine). Run: `rg -n "\bshe\b|\bher\b|\bit's\b" apps/visual/README.md apps/visual/.agents/skills/visual-qa/SKILL.md` for pronoun slips about Vesta.

```bash
git add apps/visual/README.md apps/visual/.agents .claude/skills apps/mobile/visual/README.md apps/web/visual/README.md .claude/workflows/product-critique.js
git commit -m "docs(visual): one README and one skill for the whole visual QA system"
```

---

### Task 11: Full verification

- [ ] **Step 1: Run every slice**

Run: `./check.sh app-visual app-web app-mobile guards`
Expected: green. If `guards` flags a comment block over 8 lines in any new file, shorten it.

- [ ] **Step 2: Capture every runner through the gallery**

Run (from `apps/`): `npm run visual:serve` in one terminal. In another: `curl -X POST http://127.0.0.1:4173/capture/web?gentle=1`, then `curl -X POST http://127.0.0.1:4173/capture/ios?gentle=1`, then `android` and `android-galaxy` (each 202; a second POST while running is 409). Watch `curl -s http://127.0.0.1:4173/status.json` show `"runner":"web"` then `"runner":"ios"`.
Expected: `.visual/capture-<runner>.log` for each; `run-status.json` ends `"state":"ready"`.

- [ ] **Step 3: Eyeball the gallery**

Open http://127.0.0.1:4173. Confirm: title "Vesta Apps QA"; sections "Mobile · Privacy" ... "Web · Onboarding", "Web · Agent settings"; a mobile card shows three phone-framed slots in one row; a web card shows two rows of three (light over dark) with a browser bar, a macOS title bar, and a phone-browser frame; every slot's `Copy ref` yields `visual-ref: <id> [<platform>]`; the four scan rows read `iOS`, `Android`, `Android · 3-button`, `Web` with `N/N` counts; report links open under `/reports/<runner>/report.html`.

- [ ] **Step 4: Confirm the store layout and that nothing else writes shots**

Run: `ls apps/visual/.visual/shots && rg -n "\.visual/shots|shots/" apps/mobile/scripts apps/web/visual --glob '!*.test.*'`
Expected: nine dirs; the only shot-path mentions in runners are `putShot` calls (no hand-built shot paths remain).

- [ ] **Step 5: Push and confirm CI**

```bash
git push origin epic/apps
gh pr checks 2126 --watch
```
Expected: `Apps · visual`, `Apps · web`, `Apps · mobile`, `merge-gate-ci` all pass.
