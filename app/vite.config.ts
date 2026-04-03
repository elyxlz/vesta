import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

import { cloudflare } from "@cloudflare/vite-plugin";

const host = process.env.TAURI_DEV_HOST;

export default defineConfig({
  plugins: [svelte(), cloudflare()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
  },
});