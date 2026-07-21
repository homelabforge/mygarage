import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'
import fs from 'node:fs'
import pkg from './package.json' with { type: 'json' }

// https://vite.dev/config/
export default defineConfig({
  define: {
    APP_VERSION: JSON.stringify(pkg.version),
  },
  // Relative base so the single prebuilt image serves under any URL prefix
  // (#107). Assets + dynamic imports resolve relative to the injected <base
  // href> / the importing chunk's URL — never a build-time absolute path.
  base: './',
  plugins: [
    react(),
    tailwindcss(),
    /**
     * sw.js lives in public/ and is copied verbatim, so it cannot import the
     * manifest. This writes the emitted font URLs into it at build time so the
     * service worker can precache them — without this the first offline launch
     * after a deploy renders fallback glyphs, defeating self-hosting.
     *
     * Vite copies public/ (including sw.js) to outDir during its
     * `renderStart` prepare-outDir step, before Rollup renders the bundle —
     * so sw.js never appears as an asset in `generateBundle`'s `bundle` map;
     * that hook is a silent no-op here. `writeBundle` runs after both that
     * copy and the chunk/asset writes, so it rewrites the already-on-disk
     * dist/sw.js directly. `bundle` still lists the hashed .woff2 files
     * (those go through Rollup's asset pipeline, unlike sw.js).
     */
    {
      name: 'mygarage-sw-font-assets',
      apply: 'build',
      writeBundle(options, bundle) {
        const fonts = Object.keys(bundle)
          .filter((f) => f.endsWith('.woff2'))
          .map((f) => `./${f}`)
        const outDir = options.dir
        if (!outDir) return
        const swPath = path.resolve(outDir, 'sw.js')
        if (!fs.existsSync(swPath)) return
        const source = fs.readFileSync(swPath, 'utf-8')
        const replaced = source.replace(
          '/*__FONT_ASSETS__*/[]',
          JSON.stringify(fonts),
        )
        if (replaced !== source) {
          fs.writeFileSync(swPath, replaced)
        }
      },
    },
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/__tests__/setup.ts',
    exclude: ['**/node_modules/**', '**/e2e/**'],
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
  build: {
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, 'index.html'),
      },
      output: {
        // Manual chunk splitting for better caching and performance
        manualChunks(id: string) {
          if (id.includes('node_modules/react-dom') || id.includes('node_modules/react/') || id.includes('node_modules/react-router-dom')) return 'react-vendor'
          if (id.includes('node_modules/recharts')) return 'charts'
          if (id.includes('node_modules/@schedule-x/') || id.includes('node_modules/temporal-polyfill') || id.includes('node_modules/date-fns')) return 'calendar'
          if (id.includes('node_modules/lucide-react') || id.includes('node_modules/sonner')) return 'ui'
          if (id.includes('node_modules/react-hook-form') || id.includes('node_modules/zod') || id.includes('node_modules/@hookform')) return 'forms'
          if (id.includes('node_modules/@tanstack/react-query')) return 'query'
          if (id.includes('node_modules/i18next') || id.includes('node_modules/react-i18next')) return 'i18n'
          if (id.includes('node_modules/axios')) return 'utils'
        },
      },
    },
    // Copy service worker to build output
    copyPublicDir: true,
  },
  server: {
    port: 3000,
    host: '0.0.0.0', // Allow access from network
    proxy: {
      '/api': {
        // Use environment variable for Docker compatibility
        target: process.env.VITE_API_URL || 'http://localhost:8686',
        changeOrigin: true,
      },
      '/health': {
        target: process.env.VITE_API_URL || 'http://localhost:8686',
        changeOrigin: true,
      },
    },
  },
})
