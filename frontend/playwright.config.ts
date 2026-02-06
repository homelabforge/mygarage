import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  globalTeardown: './e2e/global.teardown.ts',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI
    ? [['html', { open: 'never' }], ['github']]
    : [['html', { open: 'on-failure' }]],

  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'setup',
      testMatch: /global\.setup\.ts/,
    },
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        storageState: './e2e/.auth/user.json',
      },
      dependencies: ['setup'],
    },
  ],

  webServer: [
    {
      command:
        'rm -f /tmp/mygarage-e2e.db* && cd ../backend && python3 -m granian --interface asgi --host 0.0.0.0 --port 8686 app.main:app',
      port: 8686,
      reuseExistingServer: !process.env.CI,
      timeout: 30000,
      env: {
        MYGARAGE_DATABASE_URL: 'sqlite+aiosqlite:////tmp/mygarage-e2e.db',
        DATABASE_PATH: '/tmp/mygarage-e2e.db',
        MYGARAGE_TEST_MODE: 'true',
        LOG_LEVEL: 'WARNING',
      },
    },
    {
      command: 'VITE_API_URL=http://localhost:8686 bun run dev',
      port: 3000,
      reuseExistingServer: !process.env.CI,
      timeout: 15000,
    },
  ],
})
