import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// https://vite.dev/config/
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
          if (id.includes('node_modules/react-big-calendar') || id.includes('node_modules/date-fns')) return 'calendar'
          if (id.includes('node_modules/lucide-react') || id.includes('node_modules/sonner')) return 'ui'
          if (id.includes('node_modules/react-hook-form') || id.includes('node_modules/zod') || id.includes('node_modules/@hookform')) return 'forms'
          if (id.includes('node_modules/@tanstack/react-query')) return 'query'
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
