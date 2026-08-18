import path from "node:path";
import { describe, expect, it } from "vitest";
import { captureCommand, safeStaticPath } from "./server.mjs";
import { appsRoot } from "../platforms.mjs";

describe("safeStaticPath", () => {
  it("maps a pathname under the base directory and refuses traversal", () => {
    expect(safeStaticPath("/shots/ios/home.png", "/base")).toBe(
      path.resolve("/base/shots/ios/home.png"),
    );
    expect(safeStaticPath("/../etc/passwd", "/base")).toBeNull();
    expect(safeStaticPath("/", "/base")).toBe(path.resolve("/base/index.html"));
  });
});

describe("captureCommand", () => {
  it("spawns the runner's workspace script from apps/ with its args", () => {
    expect(captureCommand("android-galaxy", false)).toEqual({
      command: "npm",
      argumentsList: [
        "-w",
        "@vesta/mobile",
        "run",
        "visual:android:capture",
        "--",
        "--variant",
        "android-galaxy",
      ],
      cwd: appsRoot,
    });
  });
  it("appends the runner's own gentle arguments", () => {
    expect(captureCommand("web", true).argumentsList).toEqual([
      "-w",
      "@vesta/web",
      "run",
      "visual:capture",
      "--",
      "--workers=2",
    ]);
    expect(captureCommand("ios", true).argumentsList).toEqual([
      "-w",
      "@vesta/mobile",
      "run",
      "visual:ios:capture",
      "--",
      "--gentle",
    ]);
  });
  it("rejects an unknown runner", () => {
    expect(() => captureCommand("tv", false)).toThrow(/Unknown runner: tv/);
  });
});
