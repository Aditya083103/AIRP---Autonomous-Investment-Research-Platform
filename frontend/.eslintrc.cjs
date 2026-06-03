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
    // Point to the tsconfig used for linting (not build tsconfig)
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
    "import/resolver": {
      typescript: { alwaysTryTypes: true },
    },
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
    "react/react-in-jsx-scope": "off",          // not needed with React 17+ transform
    "react/prop-types": "off",                  // TypeScript handles this
    "react-refresh/only-export-components": [
      "warn",
      { allowConstantExport: true },
    ],

    // ── Imports ─────────────────────────────────────────────────────────────
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
    // Relax type-aware rules in config and script files
    {
      files: ["*.config.ts", "*.config.js", "vite.config.ts"],
      rules: {
        "@typescript-eslint/no-unsafe-assignment": "off",
        "@typescript-eslint/no-unsafe-call": "off",
      },
    },
  ],
};
