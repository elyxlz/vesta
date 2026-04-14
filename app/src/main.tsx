import { createRoot } from "react-dom/client";

import "./index.css";
import App from "./App.tsx";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { KeybindProvider } from "@/providers/KeybindProvider";
import { isTauri } from "@/lib/env";
import { detectPlatform } from "@/lib/platform";

const platform = detectPlatform();
const d = document.documentElement;
d.dataset.platform = platform;


if (isTauri) {
  d.classList.add("tauri");
  if (platform === "macos" || platform === "windows" || platform === "linux") {
    d.classList.add("vibrancy");
  }
  if (import.meta.env.PROD) {
    window.addEventListener("contextmenu", (e) => e.preventDefault());
  }
}

const isMacTauri = isTauri && platform === "macos";
d.style.setProperty("--titlebar-center-mt", isMacTauri ? "-0.5rem" : "0px");
d.style.setProperty("--titlebar-pt", isMacTauri ? "1.1rem" : "0rem");

await Promise.all([
  document.fonts.load("normal 400 16px 'Public Sans Variable'"),
  document.fonts.load("normal 400 16px 'Outfit Variable'"),
]);

createRoot(document.getElementById("root")!).render(
  <ThemeProvider defaultTheme={isTauri ? "light" : "system"}>
    <KeybindProvider>
      <App />
    </KeybindProvider>
  </ThemeProvider>,
);
