import { createRoot } from "react-dom/client";

import "./index.css";
import App from "./App.tsx";
import { ThemeProvider } from "@/providers/ThemeProvider";

await Promise.all([
  document.fonts.load("normal 400 16px 'Public Sans Variable'"),
  document.fonts.load("normal 400 16px 'Outfit Variable'"),
]);

createRoot(document.getElementById("root")!).render(
  <ThemeProvider>
    <App />
  </ThemeProvider>,
);
