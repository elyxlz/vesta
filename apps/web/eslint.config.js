import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import { defineConfig, globalIgnores } from "eslint/config";
import {
  baseConfig,
  boundaryCastOverride,
  reactHookRules,
} from "../eslint.base.mjs";

export default defineConfig([
  globalIgnores(["dist"]),
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      baseConfig,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    settings: {
      "import-x/resolver": {
        typescript: { project: ["tsconfig.app.json", "tsconfig.node.json"] },
      },
    },
    rules: reactHookRules,
  },
  boundaryCastOverride,
  // The vendored shadcn registry follows upstream shadcn, not this app's effect rules, and
  // its CSSProperties casts stay because the dashboard mirror compiles it without the
  // custom-property augmentation in react-css.d.ts.
  {
    files: ["src/components/ui/**/*.{ts,tsx}"],
    rules: {
      "react-refresh/only-export-components": "off",
      "react-hooks/set-state-in-effect": "off",
      "@typescript-eslint/no-unnecessary-type-assertion": "off",
    },
  },
  // Hook, store, and lib modules legitimately export non-components alongside hooks.
  {
    files: [
      "src/hooks/**/*.{ts,tsx}",
      "src/stores/**/*.{ts,tsx}",
      "src/lib/**/*.{ts,tsx}",
    ],
    rules: {
      "react-refresh/only-export-components": "off",
    },
  },
]);
