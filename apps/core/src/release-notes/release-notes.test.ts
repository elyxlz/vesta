import { describe, expect, it } from "vitest"
import {
  extractWhatsNew,
  filterReleaseNotes,
  parseReleaseNotes,
  type ReleaseNote,
} from "./release-notes"

function release(
  tag: string,
  overrides: Partial<{
    published_at: string
    prerelease: boolean
    body: string
  }> = {},
) {
  return {
    tag_name: tag,
    published_at: "2026-07-01T00:00:00Z",
    prerelease: false,
    body: "<!-- whats-new -->Something shipped.<!-- /whats-new -->",
    ...overrides,
  }
}

function note(version: string, prerelease = false): ReleaseNote {
  return {
    version,
    date: "2026-07-01T00:00:00Z",
    prerelease,
    message: "Something shipped.",
    url: `https://github.com/elyxlz/vesta/releases/tag/v${version}`,
  }
}

describe("extractWhatsNew", () => {
  it("extracts trimmed copy between the release markers", () => {
    expect(
      extractWhatsNew(
        "release blurb\n<!-- whats-new -->\nVesta now naps.\n<!-- /whats-new -->\nchangelog",
      ),
    ).toBe("Vesta now naps.")
  })

  it("rejects missing, incomplete, or empty marker blocks", () => {
    expect(extractWhatsNew("plain old release body")).toBeNull()
    expect(extractWhatsNew("<!-- whats-new -->half a block")).toBeNull()
    expect(extractWhatsNew("<!-- whats-new -->  \n<!-- /whats-new -->")).toBeNull()
  })
})

describe("parseReleaseNotes", () => {
  it("parses marked releases, strips v, and sorts numerically", () => {
    expect(
      parseReleaseNotes([release("v0.1.9"), release("v0.1.154"), release("v0.1.20")]).map(
        (entry) => entry.version,
      ),
    ).toEqual(["0.1.154", "0.1.20", "0.1.9"])
  })

  it("skips malformed releases and unmarked release bodies", () => {
    expect(
      parseReleaseNotes([
        release("v0.3.2", { body: "no markers here" }),
        release("v0.3.1"),
        { tag_name: "v0.3.0" },
        null,
      ]),
    ).toEqual([note("0.3.1")])
  })

  it("returns an empty list for a non-array response", () => {
    expect(parseReleaseNotes({ message: "rate limited" })).toEqual([])
    expect(parseReleaseNotes(null)).toEqual([])
  })
})

describe("filterReleaseNotes", () => {
  it("keeps only versions at or below the connected gateway", () => {
    expect(
      filterReleaseNotes([note("0.4.0"), note("0.3.1"), note("0.3.0")], {
        version: "0.3.1",
        channel: "stable",
      }),
    ).toEqual([note("0.3.1"), note("0.3.0")])
  })

  it("hides prereleases on stable and includes them on beta", () => {
    const notes = [note("0.3.2", true), note("0.3.1")]
    expect(
      filterReleaseNotes(notes, {
        version: "0.3.2",
        channel: "stable",
      }),
    ).toEqual([note("0.3.1")])
    expect(
      filterReleaseNotes(notes, {
        version: "0.3.2",
        channel: "beta",
      }),
    ).toEqual(notes)
  })
})
