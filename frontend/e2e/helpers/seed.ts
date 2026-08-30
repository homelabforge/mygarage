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

/**
 * A real admin session, for a spec that has to drive the API directly.
 *
 * A second hand-rolled login inside a spec is how `forms.ts` grew a helper that
 * PATCHed a route which never existed, so session handling lives here beside
 * the credentials it uses.
 */
export interface AdminSession {
  /** Cookie + CSRF headers to attach to an API call. */
  headers: Record<string, string>
  accessToken: string
  csrfToken: string
}

/**
 * Recover the session `seedAndAuthenticate` already established, WITHOUT
 * logging in again.
 *
 * ★ `/api/auth/login` IS RATE LIMITED TO FIVE ATTEMPTS A MINUTE PER IP
 * (`rate_limit_auth`), and the whole suite runs from one address in well under
 * a minute. `auth.spec.ts` spends two of those on purpose (a good login and a
 * bad one) and the setup project spends a third, so a spec that logs in for its
 * own setup passes when run alone and 429s in the full suite. That failure
 * arrives as "Login failed: 429" from a helper, which reads as a broken helper
 * rather than as a budget.
 *
 * The cookie in `storageState` is a bearer token that is still valid, and
 * `GET /auth/csrf-token` mints a fresh CSRF token from it with no limiter
 * attached. So a spec needing API credentials takes them from the session that
 * already exists rather than making a new one.
 *
 * @param request Any Playwright request context.
 * @param apiBase Absolute API root, e.g. `http://localhost:8686/api`.
 * @param authFile The storageState file `seedAndAuthenticate` wrote.
 * @returns The session, with the headers an API call needs.
 */
export async function adminSessionFromStorageState(
  request: APIRequestContext,
  apiBase: string,
  authFile: string,
): Promise<AdminSession> {
  const state = JSON.parse(readFileSync(authFile, 'utf8')) as {
    cookies?: { name: string; value: string }[]
  }
  const cookie = (state.cookies ?? []).find((entry) => entry.name === 'mygarage_token')
  if (cookie === undefined) {
    throw new Error(`No mygarage_token cookie in ${authFile}; did the setup project run?`)
  }
  const cookieHeader = `mygarage_token=${cookie.value}`

  const csrfResp = await request.get(`${apiBase}/auth/csrf-token`, {
    headers: { Cookie: cookieHeader },
  })
  expect(csrfResp.ok(), `CSRF refresh failed: ${csrfResp.status()}`).toBeTruthy()
  const csrfToken: string | null = (await csrfResp.json()).csrf_token
  // Null here means the cookie was not accepted (expired, or `auth_mode=none`),
  // which would otherwise surface much later as an unexplained 401.
  expect(csrfToken, 'the stored session did not yield a CSRF token').toBeTruthy()

  return {
    headers: { Cookie: cookieHeader, 'X-CSRF-Token': csrfToken ?? '' },
    accessToken: cookie.value,
    csrfToken: csrfToken ?? '',
  }
}

/**
 * Log the seeded admin in over the API.
 *
 * Spends one of the five-per-minute auth attempts, so it is deliberately NOT
 * exported: `adminSessionFromStorageState` is what a spec should use.
 *
 * @param request Any Playwright request context.
 * @param apiBase Absolute API root, e.g. `http://localhost:8686/api`.
 * @returns The session, with the headers an API call needs.
 */
async function loginAsAdmin(
  request: APIRequestContext,
  apiBase: string,
): Promise<AdminSession> {
  const loginResp = await request.post(`${apiBase}/auth/login`, {
    data: { username: ADMIN.username, password: ADMIN.password },
  })
  expect(loginResp.ok(), `Login failed: ${loginResp.status()}`).toBeTruthy()
  const loginData = await loginResp.json()
  return {
    headers: {
      Cookie: `mygarage_token=${loginData.access_token}`,
      'X-CSRF-Token': loginData.csrf_token,
    },
    accessToken: loginData.access_token,
    csrfToken: loginData.csrf_token,
  }
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
  const session = await loginAsAdmin(request, apiBase)
  const authHeaders = session.headers

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
      value: session.accessToken,
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
  }, session.csrfToken)

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
      // `vin` is a REQUIRED body field on FuelRecordCreate (17 chars), separate
      // from the path param. Omitting it 422s, silently leaving analytics with
      // no cost data — which the garage-analytics reskin's cost-conditional
      // charts then render empty. Keep it in the body.
      vin: TEST_VEHICLE.vin,
      date: today,
      odometer_km: '48280',
      liters: '47.318',
      cost: '43.75',
      is_full_tank: true,
    },
  })
  // 201 = created; 409 tolerated on rerun (duplicate). A 400/422 is a real
  // validation failure we must NOT swallow — it leaves analytics cost-free.
  expect(
    [201, 409].includes(resp.status()),
    `Seed fuel failed: ${resp.status()} ${await resp.text()}`,
  ).toBeTruthy()
}
