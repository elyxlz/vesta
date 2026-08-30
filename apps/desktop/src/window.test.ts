import path from "node:path";
import { describe, expect, it } from "vitest";
import { resolveBundlePath, rendererPermissionDecision } from "./window";

const WEB_DIST = path.join(path.sep, "app", "web");
const INDEX = path.join(WEB_DIST, "index.html");

describe("resolveBundlePath", () => {
  it.each<{ pathname: string; expected: string | null }>([
    { pathname: "/", expected: INDEX },
    { pathname: "/agent/ada", expected: INDEX },
    {
      pathname: "/assets/x.js",
      expected: path.join(WEB_DIST, "assets", "x.js"),
    },
    { pathname: "/../secrets.txt", expected: null },
    { pathname: "/%2e%2e/secrets.txt", expected: null },
    { pathname: "/assets/../../secrets.txt", expected: null },
    { pathname: "/../webX/secrets.txt", expected: null },
  ])("$pathname -> $expected", ({ pathname, expected }) => {
    expect(resolveBundlePath(WEB_DIST, pathname)).toBe(expected);
  });
});

describe("rendererPermissionDecision", () => {
  it.each([
    { permission: "geolocation", expected: "grant" },
    { permission: "media", expected: "media" },
    { permission: "notifications", expected: "deny" },
    { permission: "clipboard-read", expected: "deny" },
  ])("maps $permission to $expected", ({ permission, expected }) => {
    expect(rendererPermissionDecision(permission)).toBe(expected);
  });
});
