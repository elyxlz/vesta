import { describe, expect, it } from "vitest";

import { formatSnapshotSize } from "./format";

describe("formatSnapshotSize", () => {
  it.each([
    [0, "0 B"],
    [512, "512 B"],
    [1024, "1.0 KB"],
    [1536, "1.5 KB"],
    [1024 * 1024, "1.0 MB"],
    [1024 * 1024 * 1024, "1.0 GB"],
    [2_470_000_000, "2.3 GB"],
  ])("renders %i bytes as %s", (bytes, expected) => {
    expect(formatSnapshotSize(bytes)).toBe(expected);
  });
});
