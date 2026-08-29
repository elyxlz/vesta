// Exercises real DOM elements, so it runs in the jsdom project (.test.tsx include).
import { describe, expect, it } from "vitest";
import { isEditableTarget } from "./dom";

function element(html: string): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = html;
  const target = host.querySelector("[data-target]");
  if (!(target instanceof HTMLElement)) throw new Error("no target");
  return target;
}

describe("isEditableTarget", () => {
  it.each<[string, string, boolean]>([
    ["a text input", "<input data-target />", true],
    ["a textarea", "<textarea data-target></textarea>", true],
    ["a select", "<select data-target></select>", true],
    [
      "a contenteditable region",
      "<div contenteditable='true' data-target></div>",
      true,
    ],
    [
      "a span inside a contenteditable region",
      "<div contenteditable='true'><span data-target>x</span></div>",
      true,
    ],
    ["a button", "<button data-target>go</button>", false],
    ["a plain div", "<div data-target>text</div>", false],
  ])("%s", (_name, html, expected) => {
    expect(isEditableTarget(element(html))).toBe(expected);
  });

  it("is false for a null or non-element target", () => {
    expect(isEditableTarget(null)).toBe(false);
    expect(isEditableTarget(document)).toBe(false);
  });
});
