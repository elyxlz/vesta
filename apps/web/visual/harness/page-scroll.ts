import type { Page } from "@playwright/test";

// Discover the page's actual scroll surface by geometry, not card selectors.
// Chat and live logs opt out: their useful reference is the visible tail.
export async function preparePageScroll(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const candidates = [...document.querySelectorAll<HTMLElement>("*")]
      .filter((element) => {
        const box = element.getBoundingClientRect();
        return (
          !element.closest('[inert], [aria-hidden="true"]') &&
          /auto|scroll/.test(getComputedStyle(element).overflowY) &&
          element.scrollHeight > element.clientHeight + 1 &&
          box.width > innerWidth * 0.3 &&
          box.height > 200 &&
          box.bottom > 0 &&
          box.top < innerHeight
        );
      })
      .sort(
        (a, b) =>
          b.clientWidth * b.clientHeight - a.clientWidth * a.clientHeight,
      );
    const target = candidates[0];
    if (!target) return false;
    target.setAttribute("data-visual-scroll-target", "");
    target.scrollTop = 0;
    return true;
  });
}

export async function scrollPage(page: Page, offset?: number): Promise<number> {
  return page
    .locator("[data-visual-scroll-target]")
    .evaluate((element, next: number | undefined) => {
      const before = element.scrollTop;
      element.scrollTo({
        top: next ?? before + element.clientHeight * 0.8,
        behavior: "instant",
      });
      return element.scrollTop;
    }, offset);
}
