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
  it.each([
    ["agent/aria/details/provider", "details/[section].tsx"],
    ["agent/aria/logs", "logs.tsx"],
    ["agent/aria/file", "file.tsx"],
  ])("includes the real modal context for %s", async (route, screen) => {
    const app = path.join(appsRoot, "mobile/app");
    const files = (await routeFiles(app, route)).map((file) =>
      path.relative(app, file),
    );
    expect(files).toEqual([
      "_layout.tsx",
      "index.tsx",
      "agent/[name]/_layout.tsx",
      "agent/[name]/index.tsx",
      "agent/[name]/(settings)/_layout.tsx",
      "agent/[name]/(settings)/settings.tsx",
      `agent/[name]/(settings)/${screen}`,
    ]);
  });

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
  it("resolves pathless groups with their sheet anchors", async () => {
    const app = await appTree();
    await mkdir(path.join(app, "(connect)"));
    await writeFile(
      path.join(app, "(connect)/_layout.tsx"),
      'export const unstable_settings = { anchor: "connect" };',
    );
    await writeFile(
      path.join(app, "(connect)/connect.tsx"),
      "export default null;",
    );
    await writeFile(
      path.join(app, "(connect)/scan.tsx"),
      "export default null;",
    );
    expect(
      (await routeFiles(app, "scan")).map((file) => path.relative(app, file)),
    ).toEqual([
      "_layout.tsx",
      "(connect)/_layout.tsx",
      "(connect)/connect.tsx",
      "(connect)/scan.tsx",
    ]);
    expect(
      (await routeFiles(app, "connect")).map((file) =>
        path.relative(app, file),
      ),
    ).toEqual([
      "_layout.tsx",
      "(connect)/_layout.tsx",
      "(connect)/connect.tsx",
    ]);
  });
  it("does not include an unrelated group's layout for an unknown route", async () => {
    const app = await appTree();
    await mkdir(path.join(app, "(other)"));
    await writeFile(
      path.join(app, "(other)/_layout.tsx"),
      "export default null;",
    );
    expect(
      (await routeFiles(app, "missing")).map((file) =>
        path.relative(app, file),
      ),
    ).toEqual(["_layout.tsx"]);
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
