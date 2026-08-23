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

const scenario = (overrides) => ({
  id: "home",
  title: "Home",
  description: "d",
  group: "Home",
  ...overrides,
});

describe("validateRegistry", () => {
  it("normalises a family's scenarios: family tag and screenshot default", () => {
    const registry = validateRegistry(
      { version: 1, scenarios: [scenario({})] },
      "web",
    );
    expect(registry.family).toBe("web");
    expect(registry.scenarios[0]).toMatchObject({
      id: "home",
      family: "web",
      screenshot: "home.png",
    });
  });

  it("keeps an explicit screenshot name and passes family state through", () => {
    const registry = validateRegistry(
      {
        version: 1,
        scenarios: [
          scenario({
            screenshot: "start.png",
            route: "/new",
            agentStatus: "alive",
          }),
        ],
      },
      "web",
    );
    expect(registry.scenarios[0]).toMatchObject({
      screenshot: "start.png",
      route: "/new",
      agentStatus: "alive",
    });
  });

  it("rejects a bad version, id, screenshot, or a platform outside the family", () => {
    expect(() =>
      validateRegistry({ version: 2, scenarios: [scenario({})] }, "web"),
    ).toThrow(/version/);
    expect(() =>
      validateRegistry(
        { version: 1, scenarios: [scenario({ id: "Bad_Id" })] },
        "web",
      ),
    ).toThrow(/Invalid visual scenario id/);
    expect(() =>
      validateRegistry(
        { version: 1, scenarios: [scenario({ screenshot: "x.jpg" })] },
        "web",
      ),
    ).toThrow(/Invalid screenshot name/);
    expect(() =>
      validateRegistry(
        { version: 1, scenarios: [scenario({ platforms: ["ios"] })] },
        "web",
      ),
    ).toThrow(/Invalid platforms for home/);
    expect(() =>
      validateRegistry(
        { version: 1, scenarios: [scenario({}), scenario({})] },
        "web",
      ),
    ).toThrow(/Duplicate visual scenario id/);
    expect(() =>
      validateRegistry(
        { version: 1, scenarios: [scenario({ title: "" })] },
        "web",
      ),
    ).toThrow(/title/);
  });

  it("requires flows for the mobile family and checks each exists under flowRoot", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "visual-registry-"));
    await mkdir(path.join(root, "maestro"), { recursive: true });
    await writeFile(path.join(root, "maestro/a.yml"), "appId: x\n");
    const manifest = {
      version: 1,
      appId: "app",
      flows: ["maestro/a.yml"],
      scenarios: [scenario({})],
    };
    expect(() =>
      validateRegistry(manifest, "mobile", { flowRoot: root }),
    ).not.toThrow();
    expect(() =>
      validateRegistry(
        { ...manifest, flows: ["maestro/missing.yml"] },
        "mobile",
        { flowRoot: root },
      ),
    ).toThrow(/does not exist/);
    expect(() =>
      validateRegistry({ ...manifest, flows: ["../escape.yml"] }, "mobile", {
        flowRoot: root,
      }),
    ).toThrow(/escapes/);
    expect(() =>
      validateRegistry({ version: 1, scenarios: [scenario({})] }, "mobile", {
        flowRoot: root,
      }),
    ).toThrow(/at least one flow/);
  });
});

describe("platform filtering", () => {
  it("includes a scenario on every family platform unless it restricts itself", () => {
    expect(
      scenarioOnPlatform(scenario({ family: "mobile" }), "android-galaxy"),
    ).toBe(true);
    expect(
      scenarioOnPlatform(
        scenario({ family: "mobile", platforms: ["ios"] }),
        "android",
      ),
    ).toBe(false);
    expect(
      scenarioOnPlatform(
        scenario({ family: "web", platforms: ["web", "desktop"] }),
        "web-dark",
      ),
    ).toBe(false);
  });
  it("filters a registry to one platform", () => {
    const registry = validateRegistry(
      {
        version: 1,
        scenarios: [
          scenario({}),
          scenario({ id: "phone-only", platforms: ["web-narrow"] }),
        ],
      },
      "web",
    );
    expect(
      scenariosForPlatform(registry, "web").map((entry) => entry.id),
    ).toEqual(["home"]);
    expect(
      scenariosForPlatform(registry, "web-narrow").map((entry) => entry.id),
    ).toEqual(["home", "phone-only"]);
  });
  it("labels an exclusion with the platform labels it kept", () => {
    expect(excludedNote(scenario({ platforms: ["ios"] }))).toBe("iOS only");
    expect(excludedNote(scenario({ platforms: ["web", "desktop"] }))).toBe(
      "Web + Desktop only",
    );
  });
});

describe("loadRegistry and loadAllRegistries", () => {
  it("loads both shipped registries", async () => {
    const all = await loadAllRegistries();
    expect(all.mobile.family).toBe("mobile");
    expect(all.web.family).toBe("web");
    expect(all.mobile.scenarios.length).toBeGreaterThan(0);
    expect(all.web.scenarios.length).toBeGreaterThan(0);
  });
  it("loads one family by name", async () => {
    const registry = await loadRegistry("mobile");
    expect(registry.flows.length).toBeGreaterThan(0);
    expect(
      registry.scenarios.every((entry) => entry.screenshot.endsWith(".png")),
    ).toBe(true);
  });
});
