import { describe, expect, it } from "vitest";
import { parseGatewayUrl } from "./gateway-url";

describe("parseGatewayUrl", () => {
  it.each<[string, unknown, string | null]>([
    ["keeps an https origin", "https://box.example", "https://box.example"],
    [
      "keeps an http origin for local development",
      "http://localhost:39566",
      "http://localhost:39566",
    ],
    [
      "drops the trailing slash the parser adds",
      "https://box.example/",
      "https://box.example",
    ],
    [
      "keeps a path under the origin",
      "https://box.example/vesta",
      "https://box.example/vesta",
    ],
    ["rejects a javascript scheme", "javascript:alert(1)", null],
    ["rejects a javascript scheme in mixed case", "JavaScript:alert(1)", null],
    ["rejects a data scheme", "data:text/html,<script>alert(1)</script>", null],
    ["rejects a file scheme", "file:///etc/passwd", null],
    ["rejects a relative url", "/agents/fox", null],
    ["rejects an empty string", "", null],
    ["rejects a non-string", 42, null],
  ])("%s", (_name, raw, expected) => {
    expect(parseGatewayUrl(raw)).toBe(expected);
  });
});
