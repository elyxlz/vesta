import type { Page } from "@playwright/test";

const FAR_FUTURE_MS = 4102444800000;

// The saved connection every scenario starts from. The browser path reads it
// from localStorage; the desktop path reads it from the native store, which
// the native stub seeds with this same value.
export const VISUAL_CONNECTION = {
  url: "http://vestad.local",
  accessToken: "visual-access-token",
  refreshToken: "visual-refresh-token",
  expiresAt: FAR_FUTURE_MS,
};

// The theme is seeded as "system" so the page follows the emulated color
// scheme: the runner captures light, flips the scheme, and captures dark from
// the same driven page.
export async function seedStorage(page: Page): Promise<void> {
  await page.addInitScript((connection) => {
    localStorage.setItem("vesta-connection", JSON.stringify(connection));
    localStorage.setItem("theme", "system");
    sessionStorage.removeItem("vesta:onboarding");
  }, VISUAL_CONNECTION);
}
