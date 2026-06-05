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

  plugins: [
    "@typescript-eslint",
    "react",
    "react-hooks",
    "react-refresh",
    "import",
  ],

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
    "react-refresh/only-export-components": [
      "warn",
      { allowConstantExport: true },
    ],

    // ── Imports ─────────────────────────────────────────────────────────────
    // import/no-unresolved disabled — resolver broken on Windows with
    // eslint-import-resolver-typescript + eslint-plugin-import v2.
    // tsc --noEmit catches all real unresolved imports via strict mode.
    "import/no-unresolved": "off",
    "import/order": [
      "error",
      {
        groups: [
          "builtin",
          "external",
          "internal",
          "parent",
          "sibling",
          "index",
          "type",
        ],
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
  ],
};
