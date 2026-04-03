import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";
import path from "path";

const host = process.env.TAURI_DEV_HOST;
const vestad = process.env.VITE_VESTAD_URL || "https://localhost:7860";

export default defineConfig({
  plugins: [
    react({
      babel: {
        plugins: [["babel-plugin-react-compiler"]],
      },
    }),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  clearScreen: false,
  server: {
    port: host ? 1420 : 5173,
    strictPort: !!host,
    host: host || "0.0.0.0",
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    proxy: host
      ? undefined
      : {
          "/agents": {
            target: vestad,
            secure: false,
            ws: true,
            changeOrigin: true,
          },
          "/health": { target: vestad, secure: false, changeOrigin: true },
          "/version": { target: vestad, secure: false, changeOrigin: true },
          "/tunnel": { target: vestad, secure: false, changeOrigin: true },
        },
  },
});
