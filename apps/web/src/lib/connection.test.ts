import { describe, expect, it } from "vitest";
import { parseConnectKey } from "./connection";

describe("parseConnectKey", () => {
  it("reads the key from a vestad connect-link fragment", () => {
    expect(parseConnectKey("#k=4b80df6fdbf6de42ff4505a6")).toBe(
      "4b80df6fdbf6de42ff4505a6",
    );
  });

  it("returns null when the fragment is empty", () => {
    expect(parseConnectKey("")).toBe(null);
  });

  it("returns null for a fragment without a k param", () => {
    expect(parseConnectKey("#section")).toBe(null);
    expect(parseConnectKey("#token=abc")).toBe(null);
  });

  it("ignores other fragment params alongside the key", () => {
    expect(parseConnectKey("#foo=1&k=mykey&bar=2")).toBe("mykey");
  });
});
