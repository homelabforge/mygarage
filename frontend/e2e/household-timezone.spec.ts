import { request as apiRequest } from '@playwright/test'

import { test, expect } from './helpers/fixtures'
import { adminSessionFromStorageState, randomVin, type AdminSession } from './helpers/seed'

/**
 * The household-"today" contract (plan 4.8, R1 proof checklist).
 *
 * The browser runs in America/Chicago while the household zone is pinned to
 * UTC: the exact disagreement that made four tire specs fail between 19:00
 * and 24:00 Central. An API mount with NO date takes the server's household
 * default; the dismount drawer's UNTOUCHED date default comes from the
 * browser, which post-fix reads the same household zone from
 * `/settings/public`. The flow must succeed at ANY hour. Pre-fix it 409'd
 * (REVERSED_DATES) whenever the two zones' calendar dates disagreed; like
 * the bug, this spec only discriminates during that window, and simply
 * passes outside it.
 */

test.use({ timezoneId: 'America/Chicago' })

const ROOT_BASE_URL = 'http://localhost:3000'
const API_BASE = `${ROOT_BASE_URL}/api`
const AUTH_FILE = './e2e/.auth/user.json'

let admin: AdminSession
let previousTimezoneRow: string | null = null

test.beforeAll(async () => {
  const context = await apiRequest.newContext({ baseURL: ROOT_BASE_URL })
  try {
    admin = await adminSessionFromStorageState(context, API_BASE, AUTH_FILE)
  } finally {
    await context.dispose()
  }
})

test('a dateless API mount and an untouched UI dismount agree on "today" across zones', async ({
  page,
  request,
}) => {
  // Pin the household zone to UTC for this spec, remembering what was there.
  // Only a 404 means "no row". Anything else and the finally below would delete
  // a zone that was there all along.
  const current = await request.get(`${API_BASE}/settings/timezone`, {
    headers: admin.headers,
  })
  if (current.ok()) {
    previousTimezoneRow = (await current.json()).value ?? null
  } else {
    expect(current.status(), `read household zone: ${await current.text()}`).toBe(404)
    previousTimezoneRow = null
  }

  const vin = randomVin('THHZ')

  try {
    const pinned = await request.post(`${API_BASE}/settings/batch`, {
      headers: admin.headers,
      data: { settings: { timezone: 'UTC' } },
    })
    expect(pinned.status(), await pinned.text()).toBe(200)

    const made = await request.post(`${API_BASE}/vehicles`, {
      headers: admin.headers,
      data: { vin, nickname: 'E2E TZ Rig', vehicle_type: 'Car', year: 2020, make: 'Honda', model: 'Civic' },
    })
    expect(made.status(), await made.text()).toBe(201)

    // The mount takes the SERVER's household default; no date in the seed.
    const created = await request.post(`${API_BASE}/vehicles/${vin}/tires/create-and-mount`, {
      headers: admin.headers,
      data: { vin, position: 'FL', brand: 'E2E TZ Contract', tread_depth_mm: 8 },
    })
    expect(created.status(), await created.text()).toBe(201)

    await page.goto(`/vehicles/${vin}?tab=tires`)
    await expect(page.getByText('E2E TZ Contract')).toBeVisible({ timeout: 10000 })

    // Dismount with the drawer's UNTOUCHED date default.
    await page.getByRole('button', { name: 'Dismount' }).first().click()
    const odometer = page.locator('#dismount-odometer')
    await expect(odometer).toBeVisible({ timeout: 5000 })
    await odometer.fill('9000')
    await page.getByRole('button', { name: 'Dismount', exact: true }).last().click()

    const card = page.locator('.rounded-card', { hasText: 'E2E TZ Contract' }).first()
    await expect(card).toBeVisible({ timeout: 10000 })
    await expect(card.getByText('In storage', { exact: true })).toBeVisible()
  } finally {
    // Return the instance's zone to what it was, and drop the rig even if that
    // fails. A zone left on UTC skews "today" for every spec after this one.
    const failures: string[] = []
    if (previousTimezoneRow === null) {
      const cleared = await request.delete(`${API_BASE}/settings/timezone`, { headers: admin.headers })
      if (!cleared.ok() && cleared.status() !== 404) failures.push(`delete household zone: ${cleared.status()}`)
    } else {
      const restored = await request.post(`${API_BASE}/settings/batch`, {
        headers: admin.headers,
        data: { settings: { timezone: previousTimezoneRow } },
      })
      if (!restored.ok()) failures.push(`restore household zone ${previousTimezoneRow}: ${restored.status()}`)
    }
    const gone = await request.delete(`${API_BASE}/vehicles/${vin}`, { headers: admin.headers })
    if (!gone.ok() && gone.status() !== 404) failures.push(`vehicle ${vin}: ${gone.status()}`)
    // Soft, so a failure in the test body above still reports as itself.
    expect.soft(failures, 'cleanup left rows behind').toEqual([])
  }
})
