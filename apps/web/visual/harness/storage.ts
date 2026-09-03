import type { Page } from "@playwright/test";

const FAR_FUTURE_MS = 4102444800000;

// The saved connection every connected scenario starts from. The browser path
// reads it from localStorage; the desktop path reads it from the native store,
// which the native stub seeds with this same value.
export const VISUAL_CONNECTION = {
  url: "http://vestad.local",
  accessToken: "visual-access-token",
  refreshToken: "visual-refresh-token",
  expiresAt: FAR_FUTURE_MS,
};

// The theme is seeded as "system" so the page follows the emulated color
// scheme: the runner captures light, flips the scheme, and captures dark from
// the same driven page. `connection: false` leaves the client signed out.
export async function seedStorage(
  page: Page,
  options: { connection?: boolean; extra?: Record<string, string> } = {},
): Promise<void> {
  await page.addInitScript(
    ({ connection, extra }) => {
      if (connection) {
        localStorage.setItem("vesta-connection", JSON.stringify(connection));
      }
      localStorage.setItem("theme", "system");
      for (const [key, value] of Object.entries(extra)) {
        localStorage.setItem(key, value);
      }
      sessionStorage.removeItem("vesta:onboarding");
    },
    {
      connection: options.connection === false ? null : VISUAL_CONNECTION,
      extra: options.extra ?? {},
    },
  );
}
