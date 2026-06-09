import { describe, it, expect } from "vitest";
import { buildTtsStreamUrl } from "@/lib/voice";

describe("buildTtsStreamUrl", () => {
  it("carries the auth token in the query string (media elements can't send headers)", () => {
    const url = buildTtsStreamUrl(
      "https://host:8443",
      "tok-123",
      "my-agent",
      "abc123",
    );
    expect(url).toBe(
      "https://host:8443/agents/my-agent/voice/tts/stream/abc123?token=tok-123",
    );
  });

  it("encodes the agent name and id", () => {
    const url = buildTtsStreamUrl(
      "https://host:8443",
      "tok-123",
      "my agent",
      "a/b+c",
    );
    expect(url).toContain("/agents/my%20agent/voice/tts/stream/a%2Fb%2Bc?");
  });

  it("encodes a token with url-unsafe characters", () => {
    const url = buildTtsStreamUrl("https://h", "a b+c", "agent", "id");
    expect(url).toContain("?token=a+b%2Bc");
  });
});
