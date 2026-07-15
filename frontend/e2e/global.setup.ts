import { test as setup } from '@playwright/test'

import { TEST_VEHICLE, seedAndAuthenticate } from './helpers/seed'

// Re-exported for specs that import TEST_VEHICLE from the setup module.
export { TEST_VEHICLE }

const AUTH_FILE = './e2e/.auth/user.json'
// Parameterized (#107): the subpath project overrides this via E2E_API_BASE so
// the same seed flow runs through the prefix-stripping proxy. Default is the
// root backend, so the root project's behavior is unchanged.
const API_BASE = process.env.E2E_API_BASE ?? 'http://localhost:8686/api'

setup('create admin account and authenticate', async ({ page, request }) => {
  await seedAndAuthenticate(page, request, {
    apiBase: API_BASE,
    cookieDomain: 'localhost',
    authFile: AUTH_FILE,
  })
})
