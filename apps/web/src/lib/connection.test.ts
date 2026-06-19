import { describe, expect, it } from "vitest";
import { parseConnectKey, parseConnectLink } from "./connection";

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

describe("parseConnectLink", () => {
  it("splits a remote connect link into origin and key", () => {
    expect(
      parseConnectLink("https://fox-endeavour.vesta.run/app#k=abc123"),
    ).toEqual({ host: "https://fox-endeavour.vesta.run", key: "abc123" });
  });

  it("splits a local connect link into origin and key", () => {
    expect(parseConnectLink("http://localhost:39566/app#k=abc123")).toEqual({
      host: "http://localhost:39566",
      key: "abc123",
    });
  });

  it("trims surrounding whitespace from a pasted link", () => {
    expect(parseConnectLink("  https://fox.vesta.run/app#k=abc123\n")).toEqual({
      host: "https://fox.vesta.run",
      key: "abc123",
    });
  });

  it("returns null for a bare host with no key fragment", () => {
    expect(parseConnectLink("https://fox.vesta.run")).toBe(null);
  });

  it("returns null for an empty string", () => {
    expect(parseConnectLink("")).toBe(null);
  });
});
