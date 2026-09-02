import reactHooks from "eslint-plugin-react-hooks";
import { defineConfig } from "eslint/config";
import {
  baseConfig,
  boundaryCastOverride,
  reactHookRules,
} from "../eslint.base.mjs";

export default defineConfig([
  {
    files: ["**/*.{ts,tsx}"],
    extends: [baseConfig],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    settings: {
      "import-x/resolver": { typescript: { project: ["tsconfig.json"] } },
    },
  },
  {
    files: ["src/react/**/*.{ts,tsx}"],
    extends: [reactHooks.configs.flat.recommended],
    rules: reactHookRules,
  },
  boundaryCastOverride,
]);
