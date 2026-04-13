import { createRoot } from "react-dom/client";
import "./index.css";
import { initParentBridge } from "./lib/parent-bridge";
import App from "./App";

initParentBridge();

createRoot(document.getElementById("root")!).render(
  <App />
);
