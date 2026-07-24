import { describe, expect, it } from "vitest";
import { renderAnsiHtml } from "./ansi-html";

describe("renderAnsiHtml", () => {
  const escapeHtml = (text: string) =>
    text.replaceAll("&", "&amp;").replaceAll("<", "&lt;");

  it("renders standard colors through canonical token variables", () => {
    expect(
      renderAnsiHtml(
        "plain \x1b[35magent\x1b[34mthinking\x1b[0m plain",
        escapeHtml,
      ),
    ).toBe(
      'plain <span style="color:var(--ansi-magenta)">agent</span><span style="color:var(--ansi-blue)">thinking</span> plain',
    );
  });

  it("renders terminal attributes and extended colors", () => {
    expect(
      renderAnsiHtml("\x1b[1;2;38;5;196mimportant\x1b[0m", escapeHtml),
    ).toBe(
      '<span style="color:rgb(255, 0, 0);font-weight:700;opacity:0.62">important</span>',
    );
  });

  it("swaps foreground and background under inverse", () => {
    expect(renderAnsiHtml("\x1b[7;31minverse\x1b[0m", escapeHtml)).toBe(
      '<span style="color:var(--ansi-black);background-color:var(--ansi-red)">inverse</span>',
    );
  });

  it("delegates text escaping and removes non-style controls", () => {
    expect(renderAnsiHtml("\x1b]0;title\x07\x1b[36m<script>", escapeHtml)).toBe(
      '<span style="color:var(--ansi-cyan)">&lt;script></span>',
    );
  });
});
