import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import basicSsl from "@vitejs/plugin-basic-ssl";
import { defineConfig } from "vite";
import path from "path";
import pkg from "./package.json" with { type: "json" };

const host = process.env.TAURI_DEV_HOST;
const vestad = process.env.VITE_VESTAD_URL || "https://localhost:7860";

const isTauri = !!process.env.TAURI_ENV_PLATFORM;

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  plugins: [
    react({
      babel: {
        plugins: [["babel-plugin-react-compiler"]],
      },
    }),
    tailwindcss(),
    ...(!isTauri ? [basicSsl()] : []),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
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
