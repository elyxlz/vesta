import { describe, expect, it } from "vitest";
import { frameHtml, galleryView } from "./view.mjs";
import { galleryHtml } from "./page.mjs";

const mobileScenario = {
  id: "home",
  title: "Home",
  description: "The home screen.",
  group: "Home",
  screenshot: "home.png",
  family: "mobile",
};
const webScenario = {
  id: "name-empty",
  title: "Empty name",
  description: "The name step.",
  group: "Onboarding",
  screenshot: "name-empty.png",
  family: "web",
};
const shots = {
  ios: {
    "home.png": {
      src: "shots/ios/home.png",
      mtime: 1000,
      size: { width: 603, height: 1311 },
    },
  },
  web: {
    "name-empty.png": { src: "shots/web/name-empty.png", mtime: 2000, size: null },
  },
};

describe("galleryView", () => {
  it("renders one slot per family platform for every scenario", () => {
    const view = galleryView([mobileScenario, webScenario], shots);
    const [mobile, web] = view.sections;
    expect(mobile.scenarios[0].slots.map((slot) => slot.platform)).toEqual([
      "ios",
      "android",
      "android-galaxy",
      "ios-dark",
      "android-dark",
      "android-galaxy-dark",
    ]);
    expect(web.scenarios[0].slots.map((slot) => slot.platform)).toEqual([
      "web",
      "desktop",
      "web-narrow",
      "web-dark",
      "desktop-dark",
      "web-narrow-dark",
    ]);
  });

  it("keys sections by family and group in registry order, mobile first", () => {
    const view = galleryView([webScenario, mobileScenario], shots);
    expect(view.sections.map((section) => section.key)).toEqual([
      "Mobile · Home",
      "Web · Onboarding",
    ]);
    expect(view.sections[0]).toMatchObject({
      family: "mobile",
      familyLabel: "Mobile",
      group: "Home",
    });
  });

  it("fills a captured slot from its shot entry and marks the rest", () => {
    const view = galleryView([mobileScenario], shots);
    const [ios, android] = view.sections[0].scenarios[0].slots;
    expect(ios).toMatchObject({
      state: "captured",
      src: "shots/ios/home.png",
      mtime: 1000,
      frame: "phone",
      theme: "light",
    });
    expect(android).toMatchObject({ state: "missing", note: "Not captured yet", frame: "android-phone" });
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
    expect(frameHtml("desktop-window", "<i>s</i>")).toContain(
      'class="titlebar"',
    );
    expect(frameHtml("phone-browser", "<i>s</i>")).toContain(
      'class="frame frame-phone frame-phone-browser"',
    );
    expect(frameHtml("android-phone", "<i>s</i>")).toContain('class="frame frame-android"');
    expect(frameHtml("android-phone", "<i>s</i>")).toContain('class="punch-hole"');
    expect(frameHtml("phone", "<i>s</i>")).toContain("<i>s</i>");
  });
});

describe("galleryHtml", () => {
  const view = galleryView([mobileScenario, webScenario], shots, {
    git: { revision: "abc1234", dirty: true },
    reports: [{ label: "iOS report", href: "reports/ios/report.html" }],
  });
  const html = galleryHtml(view);

  it("titles the page for every app and stamps the revision", () => {
    expect(html).toContain("<title>Vesta Apps QA</title>");
    expect(html).toContain('data-revision="abc1234"');
    expect(html).toContain("abc1234 · dirty");
  });

  it("renders sections with family and group, and cards with one theme's columns", () => {
    expect(html).toContain('data-section-group="Mobile · Home"');
    expect(html).toContain('data-family="web"');
    expect(html).toContain('style="--shots: 3"');
    expect(html.match(/<article class="card" data-themes="light dark">/g)).toHaveLength(2);
  });

  it("tags every slot with its theme and offers the Dark toggle", () => {
    expect(html).toContain('data-platform="web-dark" data-state="missing" data-scenario-id="name-empty"');
    expect(html).toContain('data-runner="web" data-theme="dark"');
    expect(html).toContain('id="theme-toggle"');
  });

  it("annotates each shot for the shots.json poll and copy references", () => {
    expect(html).toContain(
      'data-screenshot="home.png" data-platform="ios" data-state="captured" data-scenario-id="home"',
    );
    expect(html).toContain('src="shots/ios/home.png?v=1000" data-stamp="1000"');
    expect(html).toContain('data-platform="web-dark" data-state="missing"');
  });

  it("renders a scan row per runner, not per platform", () => {
    expect(html.match(/class="scan-row"/g)).toHaveLength(4);
    expect(html).toContain('data-runner="web"');
    expect(html).not.toContain('data-runner="web-dark"');
  });

  it("renders a side navigation with a macro entry per family and a link per section", () => {
    expect(html).toContain('<nav class="side" aria-label="Gallery">');
    expect(html).toContain('<div class="side-family" data-family="mobile">');
    expect(html).toContain('<div class="side-family" data-family="web">');
    expect(html).toContain('href="#scenario-section-0" data-section="scenario-section-0"');
    expect(html).toContain('<details class="scenario-section" id="scenario-section-1"');
  });

  it("links the runner reports it was given and the static assets", () => {
    expect(html).toContain('href="reports/ios/report.html"');
    expect(html).toContain('href="gallery/styles.css"');
    expect(html).toContain('src="gallery/client.js"');
  });
});
