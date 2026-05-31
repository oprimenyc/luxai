// @ts-check
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactPlugin from "eslint-plugin-react";
import reactHooksPlugin from "eslint-plugin-react-hooks";
import unicornPlugin from "eslint-plugin-unicorn";

/** @type {import("typescript-eslint").ConfigArray} */
export const baseConfig = tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,
  {
    plugins: {
      unicorn: unicornPlugin,
    },
    rules: {
      "@typescript-eslint/consistent-type-imports": [
        "error",
        { prefer: "type-imports", fixStyle: "inline-type-imports" },
      ],
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-non-null-assertion": "warn",
      "@typescript-eslint/no-unsafe-assignment": "warn",
      "@typescript-eslint/no-unsafe-argument": "warn",
      "@typescript-eslint/no-unsafe-call": "warn",
      "@typescript-eslint/no-unsafe-member-access": "warn",
      "@typescript-eslint/no-unsafe-return": "warn",
      "@typescript-eslint/restrict-template-expressions": "warn",
      "@typescript-eslint/no-unnecessary-condition": "warn",
      "@typescript-eslint/no-deprecated": "warn",
      "@typescript-eslint/dot-notation": "warn",
      "@typescript-eslint/require-await": "warn",
      "@typescript-eslint/no-empty-object-type": "warn",
      "unicorn/filename-case": [
        "error",
        { cases: { kebabCase: true, camelCase: true, pascalCase: true } },
      ],
      "unicorn/no-array-for-each": "error",
      "unicorn/prefer-node-protocol": "error",
    },
  },
);

/** @type {import("typescript-eslint").ConfigArray} */
export const reactConfig = tseslint.config(...baseConfig, {
  plugins: {
    react: reactPlugin,
    "react-hooks": reactHooksPlugin,
  },
  rules: {
    ...reactPlugin.configs.recommended.rules,
    ...reactHooksPlugin.configs.recommended.rules,
    "react/react-in-jsx-scope": "off",
    "react/prop-types": "off",
    "react-hooks/rules-of-hooks": "error",
    "react-hooks/exhaustive-deps": "warn",
  },
  settings: {
    react: { version: "detect" },
  },
});
