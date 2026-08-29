import { describe, it, expect } from "vitest";
import { compareVersions } from "@/lib/version";

describe("compareVersions", () => {
  it.each<[string, string, string, number]>([
    ["compares numerically, not lexicographically", "0.1.154", "0.1.9", 1],
    ["orders the same pair in reverse", "0.1.9", "0.1.154", -1],
    ["compares within a single segment", "0.2.10", "0.2.9", 1],
    ["returns 0 for equal versions", "0.1.0", "0.1.0", 0],
    ["treats missing segments as zero", "1.2", "1.2.0", 0],
    ["ranks a fuller version above its prefix", "1.2.1", "1.2", 1],
    [
      "parses prerelease suffixes via their leading integer",
      "0.2.0-rc1",
      "0.1.0",
      1,
    ],
    ["ranks a lower minor below a higher one", "0.1.0", "0.2.0", -1],
  ])("%s", (_name, a, b, expected) => {
    expect(compareVersions(a, b)).toBe(expected);
  });
});
