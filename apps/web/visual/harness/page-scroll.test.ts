// @vitest-environment jsdom
import type { Page } from "@playwright/test";
import { afterEach, expect, it } from "vitest";
import { preparePageScroll, scrollPage } from "./page-scroll";

const page = {
  evaluate: (script: () => unknown) => Promise.resolve(script()),
  locator: (selector: string) => ({
    evaluate: (
      script: (element: Element, next: number | undefined) => unknown,
      next?: number,
    ) => {
      const element = document.querySelector(selector);
      if (!element) throw new Error("Missing scroll surface");
      return Promise.resolve(script(element, next));
    },
  }),
} as unknown as Page;

function surface(height: number, contentHeight: number): HTMLElement {
  const element = document.createElement("main");
  element.style.overflowY = "auto";
  Object.defineProperties(element, {
    clientHeight: { value: height },
    clientWidth: { value: 800 },
    scrollHeight: { value: contentHeight },
  });
  element.getBoundingClientRect = () => new DOMRect(0, 0, 800, height);
  element.scrollTo = (options?: ScrollToOptions | number) => {
    if (typeof options === "number") throw new Error("Expected scroll options");
    element.scrollTop = Math.min(contentHeight - height, options?.top ?? 0);
  };
  document.body.appendChild(element);
  return element;
}

afterEach(() => document.body.replaceChildren());

it("covers content added below the fold without knowing any card names", async () => {
  surface(600, 1600);
  expect(await preparePageScroll(page)).toBe(true);
  expect(await scrollPage(page)).toBe(480);
  expect(await scrollPage(page)).toBe(960);
  expect(await scrollPage(page)).toBe(1000);
  expect(await scrollPage(page)).toBe(1000);
  expect(await scrollPage(page, 0)).toBe(0);
});

it("ignores a hidden background scroll area behind a modal", async () => {
  surface(800, 2000).setAttribute("aria-hidden", "true");
  const modal = surface(400, 700);
  expect(await preparePageScroll(page)).toBe(true);
  expect(modal.hasAttribute("data-visual-scroll-target")).toBe(true);
  expect(await scrollPage(page)).toBe(300);
});

it("does not invent extra viewports for a page that fits", async () => {
  surface(600, 600);
  expect(await preparePageScroll(page)).toBe(false);
});
