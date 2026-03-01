import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

export default {
  preprocess: vitePreprocess(),
  onwarn: (warning, handler) => {
    if (warning.message.includes("corner-shape")) return;
    handler(warning);
  },
};
