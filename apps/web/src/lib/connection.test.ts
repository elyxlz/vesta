import { describe, expect, it } from "vitest";
import { parseConnectKey, parseConnectLink } from "./connection";

describe("parseConnectKey", () => {
  it.each<[string, string, string | null]>([
    [
      "reads the key from a vestad connect-link fragment",
      "#k=4b80df6fdbf6de42ff4505a6",
      "4b80df6fdbf6de42ff4505a6",
    ],
    ["returns null when the fragment is empty", "", null],
    ["returns null for a fragment without a k param", "#section", null],
    ["returns null for a token-only fragment", "#token=abc", null],
    [
      "ignores other fragment params alongside the key",
      "#foo=1&k=mykey&bar=2",
      "mykey",
    ],
  ])("%s", (_name, fragment, expected) => {
    expect(parseConnectKey(fragment)).toBe(expected);
  });
});

describe("parseConnectLink", () => {
  it.each<[string, string, { host: string; key: string } | null]>([
    [
      "splits a remote connect link into origin and key",
      "https://fox-endeavour.vesta.run/app#k=abc123",
      { host: "https://fox-endeavour.vesta.run", key: "abc123" },
    ],
    [
      "splits a local connect link into origin and key",
      "http://localhost:39566/app#k=abc123",
      { host: "http://localhost:39566", key: "abc123" },
    ],
    [
      "trims surrounding whitespace from a pasted link",
      "  https://fox.vesta.run/app#k=abc123\n",
      { host: "https://fox.vesta.run", key: "abc123" },
    ],
    [
      "returns null for a bare host with no key fragment",
      "https://fox.vesta.run",
      null,
    ],
    ["returns null for an empty string", "", null],
  ])("%s", (_name, link, expected) => {
    expect(parseConnectLink(link)).toEqual(expected);
  });
});
