import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  captureCommand,
  handleRequest,
  isRunner,
  safeStaticPath,
} from "./server.mjs";
import { appsRoot } from "../platforms.mjs";

function fakeResponse() {
  const response = {
    status: null,
    body: "",
    headersSent: false,
    writeHead(status) {
      response.status = status;
      response.headersSent = true;
      return response;
    },
    end(body = "") {
      response.body += body;
      return response;
    },
  };
  return response;
}

describe("handleRequest", () => {
  it("answers 500 to a malformed escape instead of rejecting", async () => {
    const response = fakeResponse();
    await handleRequest({ url: "/%", method: "GET" }, response, { runs: {} });
    expect(response.status).toBe(500);
    expect(response.body).toMatch(/URI malformed/);
  });
  it("refuses a prototype key as a runner name", async () => {
    expect(isRunner("constructor")).toBe(false);
    expect(isRunner("web")).toBe(true);
    const response = fakeResponse();
    await handleRequest(
      { url: "/reports/constructor/index.html", method: "GET" },
      response,
      { runs: {} },
    );
    expect(response.status).toBe(404);
  });
});

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
    const plan = captureCommand("android-galaxy", false);
    expect(plan.command).toBe("npm");
    expect(plan.argumentsList).toEqual([
      "-w",
      "@vesta/mobile",
      "run",
      "visual:android:capture",
      "--",
      "--variant",
      "android-galaxy",
    ]);
    expect(plan.cwd).toBe(appsRoot);
    expect(plan.env.VISUAL_CAPTURE_ALL).toBeUndefined();
  });
  it("asks the runner to retake everything through the environment", () => {
    expect(captureCommand("web", false, true).env.VISUAL_CAPTURE_ALL).toBe("1");
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
