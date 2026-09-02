import { describe, expect, it } from "vitest";

import { encodeFrame, reauthFrame } from "./frames";

describe("client frame constructors", () => {
  it("builds a reauth frame", () => {
    expect(reauthFrame("tok")).toEqual({ type: "reauth", token: "tok" });
  });

  it("encodes a client frame as JSON", () => {
    expect(encodeFrame(reauthFrame("tok"))).toBe(
      '{"type":"reauth","token":"tok"}',
    );
  });
});
