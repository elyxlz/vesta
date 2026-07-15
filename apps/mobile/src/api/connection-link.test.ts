import { describe, expect, it } from "vitest";
import { parseConnectLink } from "./connection-link";

describe("parseConnectLink", () => {
  it("accepts a trusted HTTPS tunnel link", () => {
    expect(parseConnectLink("https://agent.example.com/app#k=secret")).toEqual({
      ok: true,
      url: "https://agent.example.com",
      key: "secret",
    });
  });

  it.each([
    "http://agent.example.com/app#k=secret",
    "https://localhost:8443/app#k=secret",
    "https://192.168.1.2:8443/app#k=secret",
    "https://vesta.local/app#k=secret",
  ])("rejects unsupported mobile connection %s", (link) => {
    expect(parseConnectLink(link).ok).toBe(false);
  });

  it("rejects a link without a key", () => {
    expect(parseConnectLink("https://agent.example.com/app")).toEqual({
      ok: false,
      message: "This connection link has no key.",
    });
  });
});
