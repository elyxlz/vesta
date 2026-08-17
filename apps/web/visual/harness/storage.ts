import type { Page } from "@playwright/test";

const FAR_FUTURE_MS = 4102444800000;

export async function seedStorage(
  page: Page,
  theme: "dark" | "light",
): Promise<void> {
  await page.addInitScript(
    ({ pickedTheme, expiresAt }) => {
      localStorage.setItem(
        "vesta-connection",
        JSON.stringify({
          url: "http://vestad.local",
          accessToken: "visual-access-token",
          refreshToken: "visual-refresh-token",
          expiresAt,
        }),
      );
      localStorage.setItem("theme", pickedTheme);
      sessionStorage.removeItem("vesta:onboarding");
    },
    { pickedTheme: theme, expiresAt: FAR_FUTURE_MS },
  );
}
