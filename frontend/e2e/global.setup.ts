import { test as setup, expect } from '@playwright/test'

const AUTH_FILE = './e2e/.auth/user.json'
const API_BASE = 'http://localhost:8686/api'

const ADMIN = {
  username: 'e2e-admin',
  email: 'e2e@mygarage.dev',
  password: 'E2eTest!ng123',
  full_name: 'E2E Test Admin',
}

setup('create admin account and authenticate', async ({ page, request }) => {
  // Step 1: Register first user (auto-admin)
  const regResp = await request.post(`${API_BASE}/auth/register`, {
    data: {
      username: ADMIN.username,
      email: ADMIN.email,
      password: ADMIN.password,
      full_name: ADMIN.full_name,
    },
  })
  // 201 = created, 403 = already exists (rerun)
  expect([201, 403]).toContain(regResp.status())

  // Step 2: Login to get JWT + CSRF token
  const loginResp = await request.post(`${API_BASE}/auth/login`, {
    data: {
      username: ADMIN.username,
      password: ADMIN.password,
    },
  })
  expect(loginResp.ok(), `Login failed: ${loginResp.status()}`).toBeTruthy()
  const loginData = await loginResp.json()

  // Step 3: Enable local auth mode (fresh DB defaults to "none")
  const authModeResp = await request.put(`${API_BASE}/settings/auth_mode`, {
    data: { value: 'local' },
    headers: {
      Cookie: `mygarage_token=${loginData.access_token}`,
      'X-CSRF-Token': loginData.csrf_token,
    },
  })
  expect(authModeResp.ok(), `Set auth_mode failed: ${authModeResp.status()}`).toBeTruthy()

  // Step 4: Set JWT cookie on browser context
  await page.context().addCookies([
    {
      name: 'mygarage_token',
      value: loginData.access_token,
      domain: 'localhost',
      path: '/',
      httpOnly: true,
      secure: false,
      sameSite: 'Lax',
    },
  ])

  // Step 5: Set CSRF token in sessionStorage
  await page.goto('/')
  await page.evaluate((token: string) => {
    sessionStorage.setItem('csrf_token', token)
  }, loginData.csrf_token)

  // Step 6: Verify authentication works
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'Dashboard' })).toBeVisible({
    timeout: 15000,
  })

  // Save authentication state
  await page.context().storageState({ path: AUTH_FILE })
})
