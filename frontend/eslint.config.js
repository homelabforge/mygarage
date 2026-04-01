import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'node_modules'] },
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
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      // i18n guards: prevent raw currency and hardcoded locale outside utility files
      'no-restricted-syntax': [
        'warn',
        {
          selector: 'TemplateLiteral[quasis.0.value.raw=/\\$\\$/]',
          message: 'Avoid raw $ in template literals for currency. Use formatCurrency() from utils/formatUtils.ts instead.',
        },
        {
          selector: "CallExpression[callee.property.name='toLocaleDateString'][arguments.0.value='en-US']",
          message: "Avoid hardcoded 'en-US' locale. Use formatDateForDisplay() from utils/dateUtils.ts instead.",
        },
      ],
    },
  },
  // Exempt utility files from the i18n lint guards (they ARE the centralized implementation)
  {
    files: ['src/utils/formatUtils.ts', 'src/utils/units.ts', 'src/utils/dateUtils.ts'],
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
