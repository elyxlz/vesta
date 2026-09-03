import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { appsRoot } from "@vesta/visual/platforms";
import {
  flowRoutes,
  flowShots,
  routeFiles,
  sourceClosure,
} from "./visual-sources.mjs";

const FLOW = `
- openLink:
    link: "vesta-dev://agent/aria/details/provider?visualPrivacy=unlocked"
- runScript:
    file: capture-screenshot.js
    env:
      SCREENSHOT: agent-provider-none.png
- openLink:
    link: "vesta-dev://?visualPrivacy=unlocked&visualAgent=starting"
- runScript:
    env:
      SCREENSHOT: home-agent-starting.png
- openLink:
    link: "vesta-dev://agent/aria/details/provider?visualProvider=openai"
`;

describe("flow parsing", () => {
  it("lists each distinct deep-linked route once", () => {
    expect(flowRoutes(FLOW)).toEqual(["agent/aria/details/provider", ""]);
  });
  it("lists the shots a flow captures", () => {
    expect(flowShots(FLOW)).toEqual([
      "agent-provider-none.png",
      "home-agent-starting.png",
    ]);
  });
});

describe("routeFiles", () => {
  async function appTree() {
    const root = await mkdtemp(path.join(os.tmpdir(), "visual-routes-"));
    const app = path.join(root, "app");
    await mkdir(path.join(app, "agent/[name]/details"), { recursive: true });
    for (const file of [
      "_layout.tsx",
      "index.tsx",
      "settings.tsx",
      "agent/[name]/_layout.tsx",
      "agent/[name]/index.tsx",
      "agent/[name]/details/[section].tsx",
    ]) {
      await writeFile(path.join(app, file), "export default null;\n");
    }
    return app;
  }
  it("resolves the root index with its layout", async () => {
    const app = await appTree();
    expect(
      (await routeFiles(app, "")).map((f) => path.relative(app, f)),
    ).toEqual(["_layout.tsx", "index.tsx"]);
  });
  it("resolves a static file", async () => {
    const app = await appTree();
    expect(
      (await routeFiles(app, "settings")).map((f) => path.relative(app, f)),
    ).toEqual(["_layout.tsx", "settings.tsx"]);
  });
  it("resolves dynamic segments and nested layouts", async () => {
    const app = await appTree();
    expect(
      (await routeFiles(app, "agent/aria/details/provider")).map((f) =>
        path.relative(app, f),
      ),
    ).toEqual([
      "_layout.tsx",
      "agent/[name]/_layout.tsx",
      "agent/[name]/details/[section].tsx",
    ]);
    expect(
      (await routeFiles(app, "agent/aria")).map((f) => path.relative(app, f)),
    ).toEqual([
      "_layout.tsx",
      "agent/[name]/_layout.tsx",
      "agent/[name]/index.tsx",
    ]);
  });
});

describe("sourceClosure", () => {
  it("walks the graph and keeps only sources under apps/", () => {
    const a = path.join(appsRoot, "mobile/app/index.tsx");
    const b = path.join(appsRoot, "mobile/src/b.ts");
    const core = path.join(appsRoot, "core/src/index.ts");
    const dependency = path.join(appsRoot, "node_modules/react/index.js");
    const graph = new Map([
      [a, [b, dependency]],
      [b, [core, a]],
      [core, []],
      [dependency, []],
    ]);
    expect(sourceClosure(graph, [a])).toEqual([
      "core/src/index.ts",
      "mobile/app/index.tsx",
      "mobile/src/b.ts",
    ]);
  });
});
