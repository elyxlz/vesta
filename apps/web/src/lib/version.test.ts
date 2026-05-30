import { describe, it, expect } from "vitest";
import { compareVersions } from "@/lib/version";

describe("compareVersions", () => {
  it("compares numerically, not lexicographically", () => {
    expect(compareVersions("0.1.154", "0.1.9")).toBe(1);
    expect(compareVersions("0.1.9", "0.1.154")).toBe(-1);
    expect(compareVersions("0.2.10", "0.2.9")).toBe(1);
  });

  it("returns 0 for equal versions", () => {
    expect(compareVersions("0.1.0", "0.1.0")).toBe(0);
  });

  it("treats missing segments as zero", () => {
    expect(compareVersions("1.2", "1.2.0")).toBe(0);
    expect(compareVersions("1.2.1", "1.2")).toBe(1);
  });

  it("parses prerelease suffixes via their leading integer", () => {
    expect(compareVersions("0.2.0-rc1", "0.1.0")).toBe(1);
    expect(compareVersions("0.1.0", "0.2.0")).toBe(-1);
  });
});
