import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

const host = process.env.TAURI_DEV_HOST;
const vestad = process.env.VITE_VESTAD_URL || "https://localhost:7860";

export default defineConfig({
  plugins: [svelte()],
  clearScreen: false,
  server: {
    port: host ? 1420 : 5173,
    strictPort: !!host,
    host: host || false,
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    proxy: host ? undefined : {
      "/agents": { target: vestad, secure: false, ws: true, changeOrigin: true },
      "/health": { target: vestad, secure: false, changeOrigin: true },
      "/version": { target: vestad, secure: false, changeOrigin: true },
      "/tunnel": { target: vestad, secure: false, changeOrigin: true },
    },
  },
});
