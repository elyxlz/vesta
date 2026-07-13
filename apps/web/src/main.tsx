import { createRoot } from "react-dom/client";

import "./index.css";
import App from "./App.tsx";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { KeybindProvider } from "@/providers/KeybindProvider";
import { native } from "@/lib/native";

const { runtime, platform } = native;
const isDesktopApp = runtime === "electron";
const d = document.documentElement;
d.dataset.platform = platform;

if (isDesktopApp) {
  d.classList.add("desktop");
  if (platform === "macos" || platform === "windows") {
    d.classList.add("vibrancy");
  }
  if (import.meta.env.PROD) {
    window.addEventListener("contextmenu", (e) => e.preventDefault());
  }
}

const isMacDesktop = isDesktopApp && platform === "macos";
d.style.setProperty("--titlebar-center-mt", isMacDesktop ? "-0.75rem" : "0px");
d.style.setProperty("--titlebar-pt", isMacDesktop ? "1.1rem" : "0rem");

await Promise.all([
  document.fonts.load("normal 400 16px 'Public Sans Variable'"),
  document.fonts.load("normal 400 16px 'Outfit Variable'"),
]);

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("missing #root element");

createRoot(rootElement).render(
  <ThemeProvider defaultTheme={isDesktopApp ? "light" : "system"}>
    <KeybindProvider>
      <App />
    </KeybindProvider>
  </ThemeProvider>,
);
