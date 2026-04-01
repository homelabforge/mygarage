import { test as setup, expect } from '@playwright/test'

const AUTH_FILE = './e2e/.auth/user.json'
const API_BASE = 'http://localhost:8686/api'

const ADMIN = {
  username: 'e2e-admin',
  email: 'e2e@mygarage.dev',
  password: 'E2eTest!ng123',
  full_name: 'E2E Test Admin',
}

/** Seeded test vehicle used by workflow specs (records, tabs, archive). */
export const TEST_VEHICLE = {
  vin: 'TEST0000000000001',
  nickname: 'E2E Test Car',
  vehicle_type: 'Car' as const,
  year: 2022,
  make: 'TestMake',
  model: 'TestModel',
  color: 'Blue',
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

  const authHeaders = {
    Cookie: `mygarage_token=${loginData.access_token}`,
    'X-CSRF-Token': loginData.csrf_token,
  }

  // Step 3: Enable local auth mode (fresh DB defaults to "none")
  const authModeResp = await request.put(`${API_BASE}/settings/auth_mode`, {
    data: { value: 'local' },
    headers: authHeaders,
  })
  expect(authModeResp.ok(), `Set auth_mode failed: ${authModeResp.status()}`).toBeTruthy()

  // Step 4: Seed a test vehicle (idempotent — skip if already exists)
  const vehicleResp = await request.post(`${API_BASE}/vehicles`, {
    data: TEST_VEHICLE,
    headers: authHeaders,
  })
  // 201 = created, 400/409/422 = already exists (rerun)
  expect(
    [201, 400, 409, 422].includes(vehicleResp.status()),
    `Seed vehicle failed: ${vehicleResp.status()} ${await vehicleResp.text()}`
  ).toBeTruthy()

  // Step 4b: Force user language to English via API
  const langResp = await request.put(`${API_BASE}/auth/me`, {
    data: { language: 'en' },
    headers: authHeaders,
  })
  expect(langResp.ok(), `Set language failed: ${langResp.status()}`).toBeTruthy()

  // Verify /auth/me returns English
  const meResp = await request.get(`${API_BASE}/auth/me`, { headers: authHeaders })
  const meData = await meResp.json()
  console.log(`[E2E Setup] /auth/me language: ${meData.language}`)

  // Step 5: Set JWT cookie on browser context
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

  // Step 6: Set CSRF token and ensure English locale in sessionStorage/localStorage
  await page.goto('/')
  await page.evaluate((token: string) => {
    sessionStorage.setItem('csrf_token', token)
    localStorage.setItem('i18nextLng', 'en')
  }, loginData.csrf_token)

  // Step 7: Verify authentication works (reload to pick up English locale)
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'Dashboard' })).toBeVisible({
    timeout: 15000,
  })

  // Save authentication state
  await page.context().storageState({ path: AUTH_FILE })
})
