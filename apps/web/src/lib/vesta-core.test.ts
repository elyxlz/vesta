import { describe, expect, it } from "vitest";

import { PROTOCOL_VERSION } from "@vesta/core";

describe("@vesta/core resolution", () => {
  it("imports the protocol version from the workspace package", () => {
    expect(PROTOCOL_VERSION).toBe(1);
  });
});
