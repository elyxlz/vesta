import { describe, it, expect } from "vitest";
import {
  extractWhatsNew,
  parseReleaseNotes,
  filterReleaseNotes,
  type ReleaseNote,
} from "@/lib/whats-new";

function release(
  tag: string,
  overrides: Partial<{
    published_at: string;
    prerelease: boolean;
    body: string;
  }> = {},
) {
  return {
    tag_name: tag,
    published_at: "2026-07-01T00:00:00Z",
    prerelease: false,
    body: "<!-- whats-new -->Something shipped.<!-- /whats-new -->",
    ...overrides,
  };
}

function note(version: string, prerelease = false): ReleaseNote {
  return {
    version,
    date: "2026-07-01T00:00:00Z",
    prerelease,
    message: "Something shipped.",
  };
}

describe("extractWhatsNew", () => {
  it("extracts the trimmed copy between the markers", () => {
    expect(
      extractWhatsNew(
        "release blurb\n<!-- whats-new -->\nVesta now naps.\n<!-- /whats-new -->\nchangelog",
      ),
    ).toBe("Vesta now naps.");
  });

  it("returns null when no markers are present", () => {
    expect(extractWhatsNew("plain old release body")).toBeNull();
  });

  it("returns null when the closing marker is missing", () => {
    expect(extractWhatsNew("<!-- whats-new -->half a block")).toBeNull();
  });

  it("returns null when the block is empty", () => {
    expect(
      extractWhatsNew("<!-- whats-new -->  \n<!-- /whats-new -->"),
    ).toBeNull();
  });
});

describe("parseReleaseNotes", () => {
  it("parses releases and strips the leading v from tags", () => {
    expect(parseReleaseNotes([release("v0.3.1")])).toEqual([note("0.3.1")]);
  });

  it("skips releases without a well-formed block", () => {
    expect(
      parseReleaseNotes([
        release("v0.3.2", { body: "no markers here" }),
        release("v0.3.1"),
        release("v0.3.0", { body: "<!-- whats-new -->dangling" }),
      ]),
    ).toEqual([note("0.3.1")]);
  });

  it("skips entries missing the expected fields", () => {
    expect(
      parseReleaseNotes([{ tag_name: "v0.3.1" }, "junk", null, 42]),
    ).toEqual([]);
  });

  it("returns empty for non-array JSON", () => {
    expect(parseReleaseNotes({ message: "rate limited" })).toEqual([]);
    expect(parseReleaseNotes(null)).toEqual([]);
  });

  it("sorts newest version first, comparing numerically", () => {
    const parsed = parseReleaseNotes([
      release("v0.1.9"),
      release("v0.1.154"),
      release("v0.1.20"),
    ]);
    expect(parsed.map((entry) => entry.version)).toEqual([
      "0.1.154",
      "0.1.20",
      "0.1.9",
    ]);
  });
});

describe("filterReleaseNotes", () => {
  it("keeps only versions at or below the connected vestad", () => {
    const notes = [note("0.4.0"), note("0.3.1"), note("0.3.0")];
    expect(
      filterReleaseNotes(notes, { version: "0.3.1", channel: "stable" }),
    ).toEqual([note("0.3.1"), note("0.3.0")]);
  });

  it("compares versions numerically, not lexicographically", () => {
    expect(
      filterReleaseNotes([note("0.1.154")], {
        version: "0.1.20",
        channel: "stable",
      }),
    ).toEqual([]);
  });

  it("hides prereleases on the stable channel", () => {
    const notes = [note("0.3.2", true), note("0.3.1")];
    expect(
      filterReleaseNotes(notes, { version: "0.3.2", channel: "stable" }),
    ).toEqual([note("0.3.1")]);
  });

  it("shows prereleases on the beta channel", () => {
    const notes = [note("0.3.2", true), note("0.3.1")];
    expect(
      filterReleaseNotes(notes, { version: "0.3.2", channel: "beta" }),
    ).toEqual([note("0.3.2", true), note("0.3.1")]);
  });
});
