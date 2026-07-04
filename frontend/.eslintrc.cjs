// frontend/.eslintrc.cjs
// CJS format required — Vite project is ESM ("type": "module") but
// ESLint v8 still loads config files as CommonJS.

/** @type {import("eslint").Linter.Config} */
module.exports = {
  root: true,

  env: {
    browser: true,
    es2022: true,
    node: true,
  },

  parser: "@typescript-eslint/parser",
  parserOptions: {
    ecmaVersion: "latest",
    sourceType: "module",
    ecmaFeatures: { jsx: true },
    project: ["./tsconfig.json"],
    tsconfigRootDir: __dirname,
  },

  plugins: ["@typescript-eslint", "react", "react-hooks", "react-refresh", "import"],

  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:@typescript-eslint/recommended-requiring-type-checking",
    "plugin:react/recommended",
    "plugin:react-hooks/recommended",
    "plugin:import/recommended",
    "plugin:import/typescript",
    // Must be LAST — disables all rules that conflict with Prettier
    "prettier",
  ],

  settings: {
    react: { version: "detect" },
    // import/resolver intentionally omitted — eslint-import-resolver-typescript
    // has a known compatibility issue with eslint-plugin-import v2 on Windows.
    // Import resolution is covered by tsc (tsconfig paths + strict mode).
    //
    // Treat "@/..." path-alias imports (tsconfig paths + vite alias) as the
    // "internal" group so import/order places them in their own block after
    // external packages, instead of lumping them in with node_modules.
    "import/internal-regex": "^@/",
  },

  rules: {
    // ── TypeScript ──────────────────────────────────────────────────────────
    "@typescript-eslint/no-unused-vars": [
      "error",
      { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
    ],
    "@typescript-eslint/consistent-type-imports": [
      "error",
      { prefer: "type-imports", fixStyle: "inline-type-imports" },
    ],
    "@typescript-eslint/no-explicit-any": "error",
    "@typescript-eslint/no-floating-promises": "error",
    "@typescript-eslint/no-misused-promises": [
      "error",
      { checksVoidReturn: { attributes: false } },
    ],

    // ── React ───────────────────────────────────────────────────────────────
    "react/react-in-jsx-scope": "off",
    "react/prop-types": "off",
    "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],

    // ── Imports ─────────────────────────────────────────────────────────────
    // import/no-unresolved disabled — resolver broken on Windows with
    // eslint-import-resolver-typescript + eslint-plugin-import v2.
    // tsc --noEmit catches all real unresolved imports via strict mode.
    "import/no-unresolved": "off",
    "import/order": [
      "error",
      {
        groups: ["builtin", "external", "internal", "parent", "sibling", "index", "type"],
        "newlines-between": "always",
        alphabetize: { order: "asc", caseInsensitive: true },
      },
    ],
    "import/no-duplicates": "error",

    // ── General ─────────────────────────────────────────────────────────────
    "no-console": ["warn", { allow: ["warn", "error"] }],
    "prefer-const": "error",
    "no-var": "error",
  },

  overrides: [
    {
      files: ["*.config.ts", "*.config.js", "vite.config.ts"],
      rules: {
        "@typescript-eslint/no-unsafe-assignment": "off",
        "@typescript-eslint/no-unsafe-call": "off",
      },
    },
    {
      // Ambient declaration files. The `/// <reference types="vite/client" />`
      // directive in src/vite-env.d.ts is the canonical, Vite-recommended way
      // to pull in import.meta.env typings and cannot be expressed as an
      // `import`, so the triple-slash rule is disabled for *.d.ts only.
      files: ["*.d.ts"],
      rules: {
        "@typescript-eslint/triple-slash-reference": "off",
      },
    },
  ],
};
