import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

// Deliberately NOT using eslint-plugin-react-hooks's `recommended` /
// `recommended-latest` config. Both bundle the newer React Compiler rule
// suite (preserve-manual-memoization, set-state-in-effect, etc.), and several
// of those flag this codebase's existing, working fetch-in-effect pattern
// (state/store.ts) as hard errors. Only the two hooks-correctness rules this
// project actually wants are enabled explicitly below.
//
// `@typescript-eslint/no-explicit-any` is left at "warn", not silenced: every
// real contract-mismatch bug found in this project so far was hidden behind
// an `any` that let a wrong field name slip past tsc. The warning is that
// same signal, surfaced instead of suppressed.

export default tseslint.config(
  { ignores: ["dist"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
);
