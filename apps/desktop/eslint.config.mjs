import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import comments from "@eslint-community/eslint-plugin-eslint-comments/configs";
import { defineConfig, globalIgnores } from "eslint/config";

export default defineConfig([
  globalIgnores(["dist-electron", "dist"]),
  {
    files: ["src/**/*.ts"],
    extends: [
      js.configs.recommended,
      tseslint.configs.strictTypeChecked,
      tseslint.configs.stylisticTypeChecked,
      comments.recommended,
    ],
    languageOptions: {
      globals: globals.node,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      // Escape hatches are banned repo-wide: no lint-suppressing comments, no ts-comment directives.
      "@eslint-community/eslint-comments/no-use": "error",
      "@typescript-eslint/ban-ts-comment": [
        "error",
        {
          "ts-expect-error": true,
          "ts-ignore": true,
          "ts-nocheck": true,
          "ts-check": false,
        },
      ],
      // Code-smell ceilings.
      complexity: ["error", 15],
      "max-params": ["error", 5],
      "max-depth": ["error", 4],
    },
  },
  {
    files: ["scripts/**/*.mjs"],
    extends: [js.configs.recommended, comments.recommended],
    languageOptions: {
      globals: globals.node,
    },
    rules: {
      "@eslint-community/eslint-comments/no-use": "error",
    },
  },
]);
