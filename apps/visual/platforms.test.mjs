import { describe, expect, it } from "vitest";
import {
  FAMILIES,
  PLATFORMS,
  RUNNERS,
  platformsOfFamily,
  themedSibling,
} from "./platforms.mjs";

describe("PLATFORMS", () => {
  it("names every platform once with a family, a theme, a frame, and a runner", () => {
    for (const [id, platform] of Object.entries(PLATFORMS)) {
      expect(id).toMatch(/^[a-z]+(?:-[a-z]+)*$/);
      expect(Object.keys(FAMILIES)).toContain(platform.family);
      expect(["light", "dark"]).toContain(platform.theme);
      expect([
        "phone",
        "pixel",
        "galaxy",
        "browser",
        "desktop-window",
        "phone-browser",
      ]).toContain(
        platform.frame,
      );
      expect(Object.keys(RUNNERS)).toContain(platform.runner);
      expect(platform.label).toBeTruthy();
    }
  });

  it("orders each family light before dark so a card shows its light slots by default", () => {
    for (const family of Object.keys(FAMILIES)) {
      const themes = platformsOfFamily(family).map(
        (platform) => PLATFORMS[platform].theme,
      );
      const firstDark = themes.indexOf("dark");
      if (firstDark === -1) continue;
      expect(themes.slice(firstDark).every((theme) => theme === "dark")).toBe(
        true,
      );
    }
  });
});

describe("RUNNERS", () => {
  it("every runner captures at least one platform", () => {
    for (const runner of Object.keys(RUNNERS)) {
      const served = Object.values(PLATFORMS).filter(
        (platform) => platform.runner === runner,
      );
      expect(served.length).toBeGreaterThan(0);
    }
  });

  it("names the workspace script a scan spawns and how gentle mode reaches it", () => {
    expect(RUNNERS.ios).toMatchObject({
      workspace: "@vesta/mobile",
      script: "visual:ios:capture",
      gentleArgs: ["--gentle"],
    });
    expect(RUNNERS["android-galaxy"].args).toEqual([
      "--variant",
      "android-galaxy",
    ]);
    expect(RUNNERS.web).toMatchObject({
      workspace: "@vesta/web",
      script: "visual:capture",
      gentleArgs: ["--workers=2"],
    });
  });

  it("names each runner's report entry page: Maestro report.html, Playwright index.html", () => {
    expect(RUNNERS.ios.reportFile).toBe("report.html");
    expect(RUNNERS.android.reportFile).toBe("report.html");
    expect(RUNNERS.web.reportFile).toBe("index.html");
  });
});

describe("lookups", () => {
  it("lists a family's platforms in table order", () => {
    expect(platformsOfFamily("mobile")).toEqual([
      "ios",
      "android",
      "android-galaxy",
      "ios-dark",
      "android-dark",
      "android-galaxy-dark",
    ]);
    expect(platformsOfFamily("web")).toEqual([
      "web",
      "desktop",
      "web-narrow",
      "web-dark",
      "desktop-dark",
      "web-narrow-dark",
    ]);
  });

  it("rejects an unknown platform id", () => {
    expect(() => themedSibling("windows", "dark")).toThrow(/Unknown platform: windows/);
  });

  it("pairs a platform with its same-frame sibling in the other theme", () => {
    expect(themedSibling("web", "dark")).toBe("web-dark");
    expect(themedSibling("desktop", "dark")).toBe("desktop-dark");
    expect(themedSibling("web-narrow-dark", "light")).toBe("web-narrow");
    expect(themedSibling("ios", "dark")).toBe("ios-dark");
    expect(themedSibling("android-galaxy", "dark")).toBe("android-galaxy-dark");
    expect(themedSibling("android-dark", "light")).toBe("android");
  });

  it("is its own sibling in its own theme", () => {
    expect(themedSibling("ios", "light")).toBe("ios");
  });
});
