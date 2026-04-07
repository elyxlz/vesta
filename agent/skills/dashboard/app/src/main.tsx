import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./globals.css";
import { initThemeSync } from "./lib/theme-sync";
import App from "./App";

initThemeSync();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
