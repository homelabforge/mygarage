import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, devices } from '@playwright/test'

// Absolute path to the built frontend, resolved independently of cwd so the
// subpath backend can serve the production shell via MYGARAGE_STATIC_DIR (#107).
const DIST_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), 'dist')

// Subpath (#107) topology: browser -> strip proxy (:3001, /mygarage) -> backend
// (:8687, MYGARAGE_ROOT_PATH=/mygarage, serving the production dist build).
const SUBPATH_PREFIX = '/mygarage'
const SUBPATH_BACKEND_PORT = 8687
const SUBPATH_PROXY_PORT = 3001
const SUBPATH_BASE_URL = `http://127.0.0.1:${SUBPATH_PROXY_PORT}${SUBPATH_PREFIX}/`

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
    locale: 'en-US',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    // ---- Root project (Vite dev server, served at "/") ------------------
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
      // Subpath specs run only under the `subpath` project (their own baseURL).
      testIgnore: /subpath\.spec\.ts/,
    },

    // ---- Subpath project (#107): production dist behind /mygarage --------
    {
      name: 'subpath-setup',
      testMatch: /subpath\.setup\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        baseURL: SUBPATH_BASE_URL,
      },
    },
    {
      name: 'subpath',
      testMatch: /subpath\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        baseURL: SUBPATH_BASE_URL,
        storageState: './e2e/.auth/subpath-user.json',
      },
      dependencies: ['subpath-setup'],
    },
  ],

  webServer: [
    // (1) Root backend — Vite dev proxies /api here.
    {
      command:
        'rm -f /tmp/mygarage-e2e.db* && cd ../backend && uv run python -m granian --interface asgi --host 0.0.0.0 --port 8686 app.main:app',
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
    // (2) Vite dev server — the root project's baseURL (http://localhost:3000).
    {
      command: 'VITE_API_URL=http://localhost:8686 bun run dev',
      port: 3000,
      reuseExistingServer: !process.env.CI,
      timeout: 15000,
    },
    // (3) Subpath backend (#107) — builds the production dist, then serves it
    // under MYGARAGE_ROOT_PATH=/mygarage with its own DB. `/health` readiness
    // is independent of dist so the poll doesn't race the build.
    {
      command:
        'rm -f /tmp/mygarage-e2e-subpath.db* && rm -rf /tmp/mygarage-e2e-subpath-data && bun run build && cd ../backend && uv run python -m granian --interface asgi --host 127.0.0.1 --port ' +
        `${SUBPATH_BACKEND_PORT} app.main:app`,
      url: `http://127.0.0.1:${SUBPATH_BACKEND_PORT}/health`,
      reuseExistingServer: !process.env.CI,
      // Generous: includes a full `vite build` before the server starts.
      timeout: 180000,
      env: {
        MYGARAGE_DATABASE_URL: 'sqlite+aiosqlite:////tmp/mygarage-e2e-subpath.db',
        DATABASE_PATH: '/tmp/mygarage-e2e-subpath.db',
        MYGARAGE_TEST_MODE: 'true',
        MYGARAGE_ROOT_PATH: SUBPATH_PREFIX,
        MYGARAGE_STATIC_DIR: DIST_DIR,
        // Writable data dirs — the default /data/photos isn't writable on the CI
        // runner, so media seeding (seedMedia: true) 500s "Upload failed" without these.
        MYGARAGE_DATA_DIR: '/tmp/mygarage-e2e-subpath-data',
        MYGARAGE_PHOTOS_DIR: '/tmp/mygarage-e2e-subpath-data/photos',
        MYGARAGE_ATTACHMENTS_DIR: '/tmp/mygarage-e2e-subpath-data/attachments',
        MYGARAGE_DOCUMENTS_DIR: '/tmp/mygarage-e2e-subpath-data/documents',
        LOG_LEVEL: 'WARNING',
      },
    },
    // (4) Strip proxy (#107) — fronts the subpath backend; the `subpath`
    // project's baseURL points here. Readiness answered locally (/__proxy_health)
    // so it can start before the backend build finishes.
    {
      command: 'node ./e2e/subpath-proxy.mjs',
      url: `http://127.0.0.1:${SUBPATH_PROXY_PORT}/__proxy_health`,
      reuseExistingServer: !process.env.CI,
      timeout: 30000,
      env: {
        PROXY_PORT: String(SUBPATH_PROXY_PORT),
        UPSTREAM_HOST: '127.0.0.1',
        UPSTREAM_PORT: String(SUBPATH_BACKEND_PORT),
        PREFIX: SUBPATH_PREFIX,
      },
    },
  ],
})
