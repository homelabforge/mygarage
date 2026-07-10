// frontend/e2e/helpers/seed.ts
//
// Shared register/login/seed/authenticate flow used by BOTH the root
// (`global.setup.ts`) and the prefixed (`subpath.setup.ts`) Playwright
// projects (#107). The two projects differ only in where the API lives and
// where the auth cookie is scoped — everything else is identical, so the
// hardcoded `localhost:8686` that used to live in `global.setup.ts` is now a
// parameter (`apiBase`) and the subpath project drives its seed through the
// prefix-stripping proxy (`http://127.0.0.1:3001/mygarage/api`).

import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { type APIRequestContext, type Page, expect } from '@playwright/test'

const HERE = path.dirname(fileURLToPath(import.meta.url))
/** A real PNG so the backend's Pillow thumbnail step succeeds on upload. */
const SAMPLE_PHOTO = path.resolve(HERE, '../../public/icon-192.png')

export const ADMIN = {
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

export interface SeedOptions {
  /** Absolute API root, e.g. `http://localhost:8686/api` (no trailing slash). */
  apiBase: string
  /** Cookie domain the browser context is served from, e.g. `localhost`. */
  cookieDomain: string
  /** storageState output path, e.g. `./e2e/.auth/user.json`. */
  authFile: string
  /**
   * When true, also upload a main photo and seed a fuel fill-up so the subpath
   * specs can assert a `<img>` and a Recharts chart render under the prefix.
   */
  seedMedia?: boolean
}

/**
 * Register the first (admin) user, enable local auth, seed the test vehicle,
 * optionally seed media/fuel, set the JWT cookie, and persist storage state.
 * Idempotent so the suite can be re-run against a warm DB.
 */
export async function seedAndAuthenticate(
  page: Page,
  request: APIRequestContext,
  opts: SeedOptions,
): Promise<void> {
  const { apiBase, cookieDomain, authFile } = opts

  // Step 1: Register first user (auto-admin). 201 = created, 403 = exists.
  const regResp = await request.post(`${apiBase}/auth/register`, {
    data: {
      username: ADMIN.username,
      email: ADMIN.email,
      password: ADMIN.password,
      full_name: ADMIN.full_name,
    },
  })
  expect([201, 403]).toContain(regResp.status())

  // Step 2: Login for JWT + CSRF token.
  const loginResp = await request.post(`${apiBase}/auth/login`, {
    data: { username: ADMIN.username, password: ADMIN.password },
  })
  expect(loginResp.ok(), `Login failed: ${loginResp.status()}`).toBeTruthy()
  const loginData = await loginResp.json()

  const authHeaders = {
    Cookie: `mygarage_token=${loginData.access_token}`,
    'X-CSRF-Token': loginData.csrf_token,
  }

  // Step 3: Enable local auth mode (fresh DB defaults to "none").
  const authModeResp = await request.put(`${apiBase}/settings/auth_mode`, {
    data: { value: 'local' },
    headers: authHeaders,
  })
  expect(authModeResp.ok(), `Set auth_mode failed: ${authModeResp.status()}`).toBeTruthy()

  // Step 4: Seed the test vehicle (idempotent).
  const vehicleResp = await request.post(`${apiBase}/vehicles`, {
    data: TEST_VEHICLE,
    headers: authHeaders,
  })
  expect(
    [201, 400, 409, 422].includes(vehicleResp.status()),
    `Seed vehicle failed: ${vehicleResp.status()} ${await vehicleResp.text()}`,
  ).toBeTruthy()

  // Step 4b: Ensure the user language is English (i18n specs may change it).
  const langResp = await request.put(`${apiBase}/auth/me`, {
    data: { language: 'en' },
    headers: authHeaders,
  })
  expect(langResp.ok(), `Set language failed: ${langResp.status()}`).toBeTruthy()

  // Step 4c (subpath only): seed a main photo + a fuel fill-up so the prefixed
  // specs have a real `<img>` and Recharts chart to assert against.
  if (opts.seedMedia) {
    await seedMainPhoto(request, apiBase, authHeaders)
    await seedFuelRecord(request, apiBase, authHeaders)
  }

  // Step 5: Set the JWT cookie on the browser context (path '/' works under a
  // prefix — the proxy strips it before the cookie is ever sent upstream).
  await page.context().addCookies([
    {
      name: 'mygarage_token',
      value: loginData.access_token,
      domain: cookieDomain,
      path: '/',
      httpOnly: true,
      secure: false,
      sameSite: 'Lax',
    },
  ])

  // Step 6: CSRF token + English locale. Navigate with a RELATIVE '.' so it
  // resolves to the project baseURL's directory (root -> `/`, subpath ->
  // `.../mygarage/`). A root-absolute '/' would escape the `/mygarage/` prefix.
  await page.goto('.')
  await page.evaluate((token: string) => {
    sessionStorage.setItem('csrf_token', token)
    localStorage.setItem('i18nextLng', 'en')
  }, loginData.csrf_token)

  // Step 7: Verify auth works (reload to pick up English locale).
  await page.goto('.')
  await expect(page.getByRole('link', { name: 'Dashboard' })).toBeVisible({
    timeout: 15000,
  })

  await page.context().storageState({ path: authFile })
}

/** Upload a main photo for the test vehicle (idempotent-ish; extra rows ok). */
async function seedMainPhoto(
  request: APIRequestContext,
  apiBase: string,
  authHeaders: Record<string, string>,
): Promise<void> {
  const resp = await request.post(`${apiBase}/vehicles/${TEST_VEHICLE.vin}/photos`, {
    headers: authHeaders,
    multipart: {
      file: {
        name: 'seed.png',
        mimeType: 'image/png',
        buffer: readFileSync(SAMPLE_PHOTO),
      },
      set_as_main: 'true',
    },
  })
  // 201 = created; 409 = already exists on rerun.
  expect(
    [201, 409].includes(resp.status()),
    `Seed photo failed: ${resp.status()} ${await resp.text()}`,
  ).toBeTruthy()
}

/** Seed a single fuel fill-up with a cost so garage analytics has chart data. */
async function seedFuelRecord(
  request: APIRequestContext,
  apiBase: string,
  authHeaders: Record<string, string>,
): Promise<void> {
  const today = new Date().toISOString().split('T')[0]
  const resp = await request.post(`${apiBase}/vehicles/${TEST_VEHICLE.vin}/fuel`, {
    headers: authHeaders,
    data: {
      date: today,
      odometer_km: '48280',
      liters: '47.318',
      cost: '43.75',
      is_full_tank: true,
    },
  })
  // 201 = created; 400/409/422 tolerated on rerun / validation drift.
  expect(
    [201, 400, 409, 422].includes(resp.status()),
    `Seed fuel failed: ${resp.status()} ${await resp.text()}`,
  ).toBeTruthy()
}
