import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  {
    ignores: ['dist', 'node_modules'],
  },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': 'off',
      'react-hooks/incompatible-library': 'off',
      // eslint-plugin-react-hooks 7.1 introduced React Compiler-derived rules
      // that flag advisory perf/conformance issues across ~40 pre-existing
      // sites. Disabled for this release; tracked for cleanup in a dedicated
      // follow-up so the refactor isn't bundled into a hotfix.
      // TODO: re-enable as 'error' once the call sites are refactored.
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/immutability': 'off',
      'react-hooks/preserve-manual-memoization': 'off',
      'react-hooks/refs': 'off',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      // The i18n validators' regexes are single-quote-only, so a double-quoted
      // t("key") or label: "English" is invisible to both gates. Zero
      // double-quoted t( exists today by luck; the reskin rewrites ~180 files.
      quotes: ['error', 'single', { avoidEscape: true, allowTemplateLiterals: true }],
      // i18n guards: prevent raw currency and hardcoded locale outside utility files
      'no-restricted-syntax': [
        'warn',
        {
          // Matches a template chunk ending in `$` immediately before an
          // interpolation — i.e. `$${amount}`.
          //
          // The previous selector was TemplateLiteral[quasis.0.value.raw=/\$\$/]
          // and never fired: it demanded TWO literal dollars, but `$${amount}`
          // produces a quasi of exactly one (`$`), the second being the start of
          // `${`. It also only inspected quasis.0, so `Total: $${x}` was invisible
          // even to the intended pattern. Verified dead against a probe file.
          //
          // tail=false restricts this to chunks followed by an interpolation, so
          // prose like `costs 5 $` is not flagged.
          selector: 'TemplateElement[tail=false][value.raw=/\\$$/]',
          message: 'Avoid raw $ in template literals for currency. Use formatCurrency() from utils/formatUtils.ts instead.',
        },
        {
          selector: "CallExpression[callee.property.name='toLocaleDateString'][arguments.0.value='en-US']",
          message: "Avoid hardcoded 'en-US' locale. Use formatDateForDisplay() from utils/dateUtils.ts instead.",
        },
      ],
    },
  },
  // openapi-typescript emits double-quoted strings and the file is regenerated
  // by CI's check:api-freshness — hand-fixing quote style would fight the
  // generator forever. Silence only `quotes`; every other rule still applies.
  {
    files: ['src/types/api.generated.ts'],
    rules: { quotes: 'off' },
  },
  // Exempt utility files from the i18n lint guards (they ARE the centralized implementation)
  {
    files: ['src/utils/formatUtils.ts', 'src/utils/units.ts', 'src/utils/dateUtils.ts'],
    rules: {
      'no-restricted-syntax': 'off',
    },
  },
  // Tests legitimately write a raw `$`: they either mock formatCurrency (and so
  // must produce its output shape) or assert against what that mock rendered.
  // Same reasoning as the utils exemption above — these stand in for the
  // implementation rather than bypassing it.
  {
    files: ['src/**/__tests__/**/*.{ts,tsx}', 'src/**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': 'off',
    },
  },
  // Exempt E2E test files from React-specific rules (Playwright, not React)
  {
    files: ['e2e/**/*.ts'],
    rules: {
      'react-hooks/rules-of-hooks': 'off',
      'react-hooks/exhaustive-deps': 'off',
      'react-refresh/only-export-components': 'off',
    },
  },
)
