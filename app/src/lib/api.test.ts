import { describe, it, expect } from "vitest";
import { isNewer } from "./api";

describe("isNewer", () => {
  it("detects newer versions", () => {
    expect(isNewer("0.1.105", "0.1.104")).toBe(true);
    expect(isNewer("0.2.0", "0.1.0")).toBe(true);
    expect(isNewer("1.0.0", "0.9.0")).toBe(true);
    expect(isNewer("0.1.10", "0.1.9")).toBe(true);
  });

  it("rejects same version", () => {
    expect(isNewer("0.1.105", "0.1.105")).toBe(false);
  });

  it("rejects downgrades", () => {
    expect(isNewer("0.1.104", "0.1.105")).toBe(false);
    expect(isNewer("0.1.0", "0.2.0")).toBe(false);
  });
});
