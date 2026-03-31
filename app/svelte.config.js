import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

export default {
  preprocess: vitePreprocess(),
  warningFilter: (warning) => {
    if (warning.code === "css_unknown_property" && warning.message.includes("corner-shape")) return false;
    return true;
  },
};
