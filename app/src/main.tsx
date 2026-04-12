import { createRoot } from "react-dom/client";

import "./index.css";
import App from "./App.tsx";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { isTauri } from "@/lib/env";
import { detectPlatform } from "@/lib/platform";

const platform = detectPlatform();
const d = document.documentElement;
d.dataset.platform = platform;
const isMacTauri = isTauri && platform === "macos";
d.style.setProperty("--titlebar-center-mt", isMacTauri ? "-0.75rem" : "0px");

if (isTauri) {
  d.classList.add("tauri");
  if (platform === "macos" || platform === "windows") {
    d.classList.add("vibrancy");
  }
}

d.style.setProperty("--titlebar-pt", isMacTauri ? "2rem" : "0rem");

const styles = getComputedStyle(d);
const safeAreaTop = parseFloat(styles.getPropertyValue("--sat-top")) || 0;
const safeAreaBottom = parseFloat(styles.getPropertyValue("--sat-bottom")) || 0;
d.style.setProperty("--safe-area-pt", safeAreaTop > 0 ? "0.5rem" : "1rem");
d.style.setProperty("--safe-area-pb", safeAreaBottom > 0 ? "0rem" : "1.5rem");

await Promise.all([
  document.fonts.load("normal 400 16px 'Public Sans Variable'"),
  document.fonts.load("normal 400 16px 'Outfit Variable'"),
]);

createRoot(document.getElementById("root")!).render(
  <ThemeProvider defaultTheme={isTauri ? "light" : "system"}>
    <App />
  </ThemeProvider>,
);
