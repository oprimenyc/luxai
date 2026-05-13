import { reactConfig } from "@luxai/config/eslint";
import tseslint from "typescript-eslint";

export default tseslint.config(
  ...reactConfig,
  {
    ignores: [
      ".next/**",
      "dist/**",
      "node_modules/**",
      "lib/api-client-react/src/generated/**",
      "lib/api-zod/src/generated/**",
      "*.config.mjs",
      "*.config.js",
    ],
  },
  {
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
);
