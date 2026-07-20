import { describe, expect, it } from "vitest"
import { clientAheadOfGateway, compareReleaseVersions } from "./release-version"

describe("compareReleaseVersions", () => {
  it.each([
    { a: "0.1.180", b: "0.1.179", expected: 1 },
    { a: "0.2.0", b: "0.1.179", expected: 1 },
    { a: "1.0.0", b: "0.9.9", expected: 1 },
    { a: "0.1.179", b: "0.1.179", expected: 0 },
    { a: "0.1.178", b: "0.1.179", expected: -1 },
    { a: "0.1.9", b: "0.1.10", expected: -1 },
    // prerelease suffixes are dropped; the numeric core decides
    { a: "0.1.180-beta.2", b: "0.1.179", expected: 1 },
    { a: "0.1.179-beta", b: "0.1.179", expected: 0 },
  ])("$a vs $b -> $expected", ({ a, b, expected }) => {
    expect(compareReleaseVersions(a, b)).toBe(expected)
  })

  it.each([
    { a: "dev", b: "0.1.0" },
    { a: "0.1.0", b: "" },
    { a: "nightly", b: "unknown" },
    { a: "0.1.x", b: "0.1.0" },
  ])("fails open (null) on unparseable $a / $b", ({ a, b }) => {
    expect(compareReleaseVersions(a, b)).toBeNull()
  })
})

describe("clientAheadOfGateway", () => {
  it("blocks only when the client is strictly newer", () => {
    expect(clientAheadOfGateway("0.2.0", "0.1.179")).toBe(true)
    expect(clientAheadOfGateway("0.1.179", "0.1.179")).toBe(false)
    expect(clientAheadOfGateway("0.1.178", "0.1.179")).toBe(false)
  })

  it("fails open when a version is unparseable so dev builds never block", () => {
    expect(clientAheadOfGateway("dev", "0.1.0")).toBe(false)
    expect(clientAheadOfGateway("0.2.0", "gateway-dev")).toBe(false)
  })
})
