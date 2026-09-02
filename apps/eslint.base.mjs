import js from "@eslint/js";
import comments from "@eslint-community/eslint-plugin-eslint-comments/configs";
import eslintConfigPrettier from "eslint-config-prettier";
import importX from "eslint-plugin-import-x";
import tseslint from "typescript-eslint";

// The one lint baseline for every TypeScript package under apps/. A package config extends
// this and adds only its framework plugins; a rule tuned for one package is tuned here.
export const baseConfig = tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,
  comments.recommended,
  importX.flatConfigs.recommended,
  importX.flatConfigs.typescript,
  {
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          destructuredArrayIgnorePattern: "^_",
        },
      ],
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
      // Code-smell ceilings. Modified cyclomatic complexity counts a switch once, so an
      // exhaustive match over a discriminant is not a smell.
      complexity: ["error", { max: 15, variant: "modified" }],
      "max-params": ["error", 5],
      "max-depth": ["error", 4],
      "import-x/no-cycle": "error",
      // Parse at the boundary; a cast is never the fix (boundary parsers are excepted below).
      "@typescript-eslint/consistent-type-assertions": [
        "error",
        { assertionStyle: "never" },
      ],
      // Arrow shorthand passing a void return through is idiomatic for event handlers.
      "@typescript-eslint/no-confusing-void-expression": [
        "error",
        { ignoreArrowShorthand: true },
      ],
    },
  },
  eslintConfigPrettier,
);

// The React compiler rules, on wherever a hook is written.
export const reactHookRules = {
  "react-hooks/refs": "error",
  "react-hooks/set-state-in-effect": "error",
  "react-hooks/purity": "error",
  "react-hooks/immutability": "error",
};

// Vendored primitives, the modules that parse untyped input (wire frames, the http and socket
// transports, the preload bridge), and test fakes are the only places a cast is the honest tool.
export const boundaryCastOverride = {
  files: [
    "src/components/ui/**",
    "src/protocol/**",
    "src/transport/**",
    "src/chat/chat-socket.ts",
    "src/voice/stt-session.ts",
    "src/lib/native/**",
    "**/*.test.{ts,tsx}",
  ],
  rules: {
    "@typescript-eslint/consistent-type-assertions": [
      "error",
      { assertionStyle: "as", objectLiteralTypeAssertions: "allow" },
    ],
  },
};
