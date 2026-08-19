import js from "@eslint/js";
import globals from "globals";
import { defineConfig, globalIgnores } from "eslint/config";

export default defineConfig([
  globalIgnores([".visual"]),
  {
    files: ["**/*.mjs"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
  {
    files: ["gallery/client.js"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.browser },
  },
]);
