import { request as apiRequest } from '@playwright/test'

import { test, expect } from './helpers/fixtures'
import { adminSessionFromStorageState, type AdminSession } from './helpers/seed'
import { TEST_VEHICLE } from './helpers/selectors'

/**
 * The tire lifecycle, driven through the browser.
 *
 * These flows had no end-to-end coverage at all before v3.3.0, which is how
 * `POST /tires` could stop accepting a `position` and only one incidental
 * settings test noticed.
 *
 * What is worth proving here rather than in a unit test: the seven new
 * response fields survive serialisation, the drawers submit shapes the API
 * accepts, and a stored tire renders as a tire rather than as a corner whose
 * label failed to resolve. All three are cross-layer and all three were
 * invisible to the component tests, which mock the hooks.
 */

const VIN = TEST_VEHICLE.vin
const ROOT_BASE_URL = 'http://localhost:3000'
const API_BASE = `${ROOT_BASE_URL}/api`
const AUTH_FILE = './e2e/.auth/user.json'

/** The admin session, resolved once for this file (see settings.spec.ts). */
let cachedAdmin: AdminSession | null = null

async function adminSession(): Promise<AdminSession> {
  if (cachedAdmin !== null) return cachedAdmin
  const context = await apiRequest.newContext({ baseURL: ROOT_BASE_URL })
  try {
    cachedAdmin = await adminSessionFromStorageState(context, API_BASE, AUTH_FILE)
    return cachedAdmin
  } finally {
    await context.dispose()
  }
}

async function openTires(page: import('@playwright/test').Page) {
  await page.goto(`/vehicles/${VIN}`)
  await expect(page.getByRole('heading', { name: TEST_VEHICLE.nickname })).toBeVisible({
    timeout: 15000,
  })
  await page.getByRole('tab', { name: 'Maintenance' }).click()
  await page.getByRole('tab', { name: 'Tires' }).click()
  await expect(page.getByRole('heading', { name: 'Tires' })).toBeVisible({ timeout: 10000 })
}

test.describe('Tires', () => {
  test('create-and-mount, then dismount, keeps the tire and frees the corner', async ({
    page,
    request,
  }) => {
    const admin = await adminSession()
    // Seeded through the API so the test is about the BROWSER flow that
    // follows, not about form-filling.
    const created = await request.post(
      `${API_BASE}/vehicles/${VIN}/tires/create-and-mount`,
      {
        headers: admin.headers,
        data: {
          vin: VIN,
          position: 'RR',
          brand: 'E2E Michelin',
          tread_depth_mm: 8,
          min_tread_mm: 2,
          mounted_odometer_km: 1000,
        },
      }
    )
    expect([201, 409], `seed failed: ${await created.text()}`).toContain(created.status())
    test.skip(created.status() === 409, 'RR already occupied by a previous run')

    await openTires(page)
    await expect(page.getByText('E2E Michelin')).toBeVisible({ timeout: 10000 })

    // Dismount through the drawer, supplying the closing odometer.
    await page
      .getByRole('button', { name: 'Dismount' })
      .first()
      .click()
    const odometer = page.locator('#dismount-odometer')
    await expect(odometer).toBeVisible({ timeout: 5000 })
    await odometer.fill('9000')
    await page
      .getByRole('button', { name: 'Dismount', exact: true })
      .last()
      .click()

    // The tire is still there, now under "In storage" -- not deleted, and not
    // rendered as a blank corner.
    await expect(page.getByText('In storage').first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('E2E Michelin')).toBeVisible()
  })

  test('a tire with no odometer bounds prompts rather than showing a zero', async ({
    page,
    request,
  }) => {
    const admin = await adminSession()
    // The upgrade-day shape: mounted, but with no odometer on the mount, so
    // there is no bounded distance. Every tire on every instance looks like
    // this the moment migration 097 runs, which is why "0 km" here would be
    // the single most visible wrong number in the release.
    const created = await request.post(
      `${API_BASE}/vehicles/${VIN}/tires/create-and-mount`,
      {
        headers: admin.headers,
        data: { vin: VIN, position: 'SPARE', brand: 'E2E Unbounded', tread_depth_mm: 7 },
      }
    )
    expect([201, 409], `seed failed: ${await created.text()}`).toContain(created.status())
    test.skip(created.status() === 409, 'SPARE already occupied by a previous run')

    const body = await created.json()
    // The contract, before the browser is involved: a spare that has never
    // rolled reports its own status and no number.
    expect(body.distance_status).toBe('spare_only')
    expect(body.distance_km).toBeNull()

    await openTires(page)
    await expect(page.getByText('E2E Unbounded')).toBeVisible({ timeout: 10000 })
    // Whatever wording the locale gives it, it must not be a zero distance.
    await expect(page.getByText(/^0 (km|mi)$/)).toHaveCount(0)
  })

  test('a stale client POSTing a position is rejected loudly', async ({ request }) => {
    const admin = await adminSession()
    // The release's breaking change, asserted as a contract rather than
    // described in a changelog. A browser tab left open across the upgrade
    // sends exactly this payload; the 422 naming the field is what stops it
    // silently creating a second, unmounted tire.
    const response = await request.post(`${API_BASE}/vehicles/${VIN}/tires`, {
      headers: admin.headers,
      data: { vin: VIN, position: 'FL', tread_depth_mm: 8 },
    })
    expect(response.status()).toBe(422)
    const detail = await response.text()
    expect(detail).toContain('position')
  })
})
