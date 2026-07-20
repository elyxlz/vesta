import { describe, expect, it } from "vitest";

import { compareReleaseVersions } from "@vesta/core";

describe("@vesta/core resolution", () => {
  it("imports the release-version compare from the file dependency", () => {
    expect(compareReleaseVersions("0.2.0", "0.1.0")).toBe(1);
  });
});
