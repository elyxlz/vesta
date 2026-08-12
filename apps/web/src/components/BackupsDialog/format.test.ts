import { describe, expect, it } from "vitest";

import {
  formatSnapshotSize,
  formatSnapshotStamp,
  parseSnapshotStamp,
} from "./format";

describe("parseSnapshotStamp", () => {
  it("reads vestad's compact stamp as the UTC moment it names", () => {
    const at = parseSnapshotStamp("20260529-040001");
    expect(at?.getTime()).toBe(Date.UTC(2026, 4, 29, 4, 0, 1));
  });

  it.each([
    ["2026-01-01T00:00:00Z", "an iso timestamp"],
    ["20260529040001", "no separator"],
    ["2026052-040001", "a short date"],
    ["", "an empty string"],
  ])("returns null for %s (%s)", (stamp) => {
    expect(parseSnapshotStamp(stamp)).toBeNull();
  });
});

describe("formatSnapshotStamp", () => {
  it("humanizes a compact stamp into a date and a time", () => {
    const shown = formatSnapshotStamp("20260529-040001");
    expect(shown).not.toContain("20260529-040001");
    expect(shown).toContain("2026");
    expect(shown).toContain("·");
  });

  it("shows an unrecognized stamp as it came, rather than an invalid date", () => {
    expect(formatSnapshotStamp("whenever")).toBe("whenever");
  });
});

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
