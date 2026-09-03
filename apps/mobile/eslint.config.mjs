import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import expoConfig from "eslint-config-expo/flat.js";
import globals from "globals";

export default defineConfig([
  expoConfig,
  {
    ignores: ["dist/*", "ios/*", "android/*", ".visual/*", ".expo/*"],
  },
  {
    files: ["**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "Literal[value=/^\\/(agents|gateway)\\//], TemplateElement[value.raw=/^\\/(agents|gateway)\\//]",
          message: "gateway routes live once in @vesta/core/src/api",
        },
      ],
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  {
    // The route wrappers themselves, the fake gateway the visual harness serves, and tests may
    // spell a gateway path.
    files: ["src/api/**", "visual/**", "**/*.test.{ts,tsx}"],
    rules: { "no-restricted-syntax": "off" },
  },
  {
    // The visual runners are plain Node ESM outside the Expo graph: the
    // recommended rules give them no-undef and no-unused-vars.
    files: ["scripts/**/*.mjs"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
  {
    // Maestro's runScript runtime injects these into the flow helper.
    files: ["maestro/**/*.js"],
    languageOptions: {
      globals: {
        http: "readonly",
        CAPTURE_URL: "readonly",
        CAPTURE_URL_1: "readonly",
        CAPTURE_URL_2: "readonly",
        MAESTRO_SHARD_INDEX: "readonly",
        ACTION: "readonly",
        SCREENSHOT: "readonly",
      },
    },
  },
]);
