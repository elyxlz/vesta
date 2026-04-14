import { readFileSync } from "fs";
import path from "path";
import { describe, expect, it } from "vitest";

describe("vite config", () => {
  it("base path must be exactly '/'", () => {
    const config = readFileSync(
      path.resolve(__dirname, "../../vite.config.ts"),
      "utf-8",
    );
    const match = config.match(/^\s*base:\s*["'](.+?)["']/m);
    expect(match).not.toBeNull();
    expect(match![1]).toBe("/");
  });
});
