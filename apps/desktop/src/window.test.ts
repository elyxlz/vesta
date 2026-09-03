import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  CONTENT_SECURITY_POLICY,
  downloadDefaultPath,
  rendererPermissionDecision,
  resolveBundlePath,
  withContentSecurityPolicy,
} from "./window";

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

describe("downloadDefaultPath", () => {
  it("preselects the Downloads folder under the item's filename", () => {
    expect(downloadDefaultPath("/home/u/Downloads", "photo.jpg")).toBe(
      "/home/u/Downloads/photo.jpg",
    );
  });

  it("never produces a bare directory for a nameless item", () => {
    expect(downloadDefaultPath("/home/u/Downloads", "")).toBe(
      "/home/u/Downloads/file",
    );
  });
});

describe("rendererPermissionDecision", () => {
  it.each<{
    permission: string;
    mediaTypes: string[] | undefined;
    expected: string;
  }>([
    { permission: "geolocation", mediaTypes: undefined, expected: "grant" },
    { permission: "media", mediaTypes: ["audio"], expected: "media" },
    { permission: "media", mediaTypes: ["video"], expected: "deny" },
    { permission: "media", mediaTypes: ["audio", "video"], expected: "deny" },
    { permission: "media", mediaTypes: undefined, expected: "deny" },
    { permission: "notifications", mediaTypes: undefined, expected: "deny" },
    { permission: "clipboard-read", mediaTypes: undefined, expected: "deny" },
  ])(
    "maps $permission $mediaTypes to $expected",
    ({ permission, mediaTypes, expected }) => {
      expect(rendererPermissionDecision(permission, mediaTypes)).toBe(expected);
    },
  );
});

describe("withContentSecurityPolicy", () => {
  it("stamps the policy on the bundle response and keeps the body", async () => {
    const response = withContentSecurityPolicy(
      new Response("<html></html>", {
        status: 200,
        headers: { "content-type": "text/html" },
      }),
    );
    expect(response.headers.get("content-security-policy")).toBe(
      CONTENT_SECURITY_POLICY,
    );
    expect(response.headers.get("content-type")).toBe("text/html");
    expect(await response.text()).toBe("<html></html>");
  });

  it("allows script only from the bundle", () => {
    expect(CONTENT_SECURITY_POLICY).toContain("script-src 'self';");
    expect(CONTENT_SECURITY_POLICY).toContain("object-src 'none'");
    expect(CONTENT_SECURITY_POLICY).not.toContain("unsafe-eval");
  });
});
