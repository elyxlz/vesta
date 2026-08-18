import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import expoConfig from "eslint-config-expo/flat.js";
import globals from "globals";

export default defineConfig([
  expoConfig,
  {
    ignores: ["dist/*", "ios/*", "android/*"],
  },
  {
    files: ["**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  {
    // The visual runners are plain Node ESM outside the Expo graph: the
    // recommended rules give them no-undef and no-unused-vars.
    files: ["scripts/**/*.mjs"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
]);
