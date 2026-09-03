import js from "@eslint/js";
import comments from "@eslint-community/eslint-plugin-eslint-comments/configs";
import globals from "globals";
import { defineConfig, globalIgnores } from "eslint/config";
import { baseConfig, boundaryCastOverride } from "../eslint.base.mjs";

export default defineConfig([
  globalIgnores(["dist-electron", "dist"]),
  {
    files: ["src/**/*.ts"],
    extends: [baseConfig],
    languageOptions: {
      globals: globals.node,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    settings: {
      "import-x/resolver": { typescript: { project: ["tsconfig.json"] } },
    },
  },
  boundaryCastOverride,
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
