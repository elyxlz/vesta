import { fileURLToPath } from "node:url";
import path from "node:path";

export const visualRoot = path.dirname(fileURLToPath(import.meta.url));
export const appsRoot = path.resolve(visualRoot, "..");

// The one owner of which capture targets exist. A platform is one gallery slot:
// a theme variant is its own platform the same way the 3-button Android persona is.
// Runner-only facts (an AVD, a viewport, a native stub) live in the runner, keyed by id.
export const PLATFORMS = {
  ios: {
    label: "iOS",
    family: "mobile",
    theme: "light",
    frame: "phone",
    runner: "ios",
  },
  android: {
    label: "Android",
    family: "mobile",
    theme: "light",
    frame: "pixel",
    runner: "android",
  },
  "android-galaxy": {
    label: "Android · 3-button",
    family: "mobile",
    theme: "light",
    frame: "galaxy",
    runner: "android-galaxy",
  },
  "ios-dark": {
    label: "iOS · dark",
    family: "mobile",
    theme: "dark",
    frame: "phone",
    runner: "ios",
  },
  "android-dark": {
    label: "Android · dark",
    family: "mobile",
    theme: "dark",
    frame: "pixel",
    runner: "android",
  },
  "android-galaxy-dark": {
    label: "Android · 3-button · dark",
    family: "mobile",
    theme: "dark",
    frame: "galaxy",
    runner: "android-galaxy",
  },
  web: {
    label: "Web",
    family: "web",
    theme: "light",
    frame: "browser",
    runner: "web",
  },
  desktop: {
    label: "Desktop",
    family: "web",
    theme: "light",
    frame: "desktop-window",
    runner: "web",
  },
  "web-narrow": {
    label: "Web · phone",
    family: "web",
    theme: "light",
    frame: "phone-browser",
    runner: "web",
  },
  "web-dark": {
    label: "Web · dark",
    family: "web",
    theme: "dark",
    frame: "browser",
    runner: "web",
  },
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
// holds the runner's own HTML report, served by the gallery under /reports/<runner>/,
// and reportFile names its entry page (Maestro writes report.html, Playwright index.html).
export const RUNNERS = {
  ios: {
    label: "iOS",
    workspace: "@vesta/mobile",
    script: "visual:ios:capture",
    args: [],
    gentleArgs: ["--gentle"],
    reportDirectory: path.join(appsRoot, "mobile/.visual/maestro"),
    reportFile: "report.html",
  },
  android: {
    label: "Android",
    workspace: "@vesta/mobile",
    script: "visual:android:capture",
    args: [],
    gentleArgs: ["--gentle"],
    reportDirectory: path.join(appsRoot, "mobile/.visual/android/maestro"),
    reportFile: "report.html",
  },
  "android-galaxy": {
    label: "Android · 3-button",
    workspace: "@vesta/mobile",
    script: "visual:android:capture",
    args: ["--variant", "android-galaxy"],
    gentleArgs: ["--gentle"],
    reportDirectory: path.join(
      appsRoot,
      "mobile/.visual/android-galaxy/maestro",
    ),
    reportFile: "report.html",
  },
  web: {
    label: "Web",
    workspace: "@vesta/web",
    script: "visual:capture",
    args: [],
    gentleArgs: ["--workers=2"],
    reportDirectory: path.join(appsRoot, "web/.visual/report"),
    reportFile: "index.html",
  },
};

export const FAMILIES = {
  mobile: {
    label: "Mobile",
    registry: path.join(appsRoot, "mobile/visual/scenarios.json"),
  },
  web: {
    label: "Web",
    registry: path.join(appsRoot, "web/visual/scenarios.json"),
  },
};

function requirePlatform(id) {
  const platform = PLATFORMS[id];
  if (!platform) throw new Error(`Unknown platform: ${id}`);
  return platform;
}

export function platformsOfFamily(family) {
  return Object.keys(PLATFORMS).filter((id) => PLATFORMS[id].family === family);
}

// The same runner and frame in another theme, or null when there is none: a
// runner flips the OS appearance in place and captures both from one drive.
export function themedSibling(id, theme) {
  const platform = requirePlatform(id);
  const match = Object.entries(PLATFORMS).find(
    ([, candidate]) =>
      candidate.runner === platform.runner &&
      candidate.frame === platform.frame &&
      candidate.theme === theme,
  );
  return match ? match[0] : null;
}
