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
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
          'charts': ['recharts'],
          'calendar': ['react-big-calendar', 'date-fns'],
          'ui': ['lucide-react', 'sonner'],
          'forms': ['react-hook-form', 'zod', '@hookform/resolvers'],
          'utils': ['axios'],
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
