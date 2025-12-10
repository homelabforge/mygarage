import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react-swc'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// TEMPORARY FIX: Explicit Vitest config for Bun compatibility
// TODO: Remove this file when Bun's Vitest integration properly loads jsdom from vite.config.ts
// Issue: Bun 1.3.4 doesn't pick up test config from vite.config.ts when running in CI
// Tracking: https://github.com/oven-sh/bun/issues (check for jsdom/vitest integration fixes)
// Expected resolution: Bun 1.4+ or Vitest update

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/__tests__/setup.ts',
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: [
        'node_modules/',
        'src/__tests__/',
        '**/*.d.ts',
        '**/*.config.{js,ts}',
        '**/mockData.ts',
      ],
    },
  },
})
