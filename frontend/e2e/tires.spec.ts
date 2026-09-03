import { request as apiRequest } from '@playwright/test'

import { test, expect } from './helpers/fixtures'
import { adminSessionFromStorageState, type AdminSession } from './helpers/seed'

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

/**
 * A vehicle created fresh for this file, on every run.
 *
 * NOT the shared TEST_VEHICLE. Two reasons, both learned the hard way:
 *
 * - Corners are claimable once now, so tests that mount tires are no longer
 *   idempotent. `reuseExistingServer` keeps the e2e backend and its database
 *   alive between local invocations, so a second run found every position
 *   taken and either skipped (proving nothing) or failed in a way that looked
 *   like a product bug.
 * - The first attempt at a per-test vehicle reused TEST_VEHICLE's make, model
 *   and year, which put a second identical card on the dashboard and broke two
 *   assertions in vehicle.spec.ts with a strict-mode violation. Distinctive
 *   make/model, so no other spec's text matcher can see it.
 */
const vehicleVins = new Map<string, string>()

async function tireVehicle(
  request: import('@playwright/test').APIRequestContext,
  label = 'default'
): Promise<string> {
  // Keyed by label so a test needing a corner another test already claimed can
  // ask for its own rig. A single shared rig is not enough: there are five
  // positions, the rotation test claims four of them and the unbounded test
  // holds SPARE, so anything else wanting a corner gets a 409 that looks like
  // a product bug.
  const cached = vehicleVins.get(label)
  if (cached !== undefined) return cached
  const admin = await adminSession()
  // 17 chars, no I/O/Q -- VIN validation rejects those.
  const vin = ('TRET' + Math.random().toString(36).slice(2).toUpperCase())
    .replace(/[IOQ]/g, 'X')
    .padEnd(17, '0')
    .slice(0, 17)
  const made = await request.post(`${API_BASE}/vehicles`, {
    headers: admin.headers,
    data: {
      vin,
      nickname: 'E2E Tire Rig',
      vehicle_type: 'Car',
      year: 1999,
      make: 'TireRigMake',
      model: 'TireRigModel',
    },
  })
  expect(
    [201, 409].includes(made.status()),
    `seed tire vehicle: ${made.status()} ${await made.text()}`
  ).toBeTruthy()
  vehicleVins.set(label, vin)
  return vin
}

async function openTires(page: import('@playwright/test').Page, vin: string) {
  await page.goto(`/vehicles/${vin}`)
  await expect(page.getByRole('heading', { name: 'E2E Tire Rig' })).toBeVisible({
    timeout: 15000,
  })
  await page.getByRole('tab', { name: 'Maintenance' }).click()
  await page.getByRole('tab', { name: 'Tires' }).click()
  // `exact` matters: without it this also matches the EmptyState's "No tires
  // tracked yet" heading, and the two together are a strict-mode violation.
  // Latent until now because every other test in this file seeded a tire
  // through the API first, so the empty state -- the state a new user is
  // actually in -- had never been rendered here.
  await expect(page.getByRole('heading', { name: 'Tires', exact: true })).toBeVisible({
    timeout: 10000,
  })
}

/**
 * Delete every rig this file created.
 *
 * Not optional tidiness: the rigs appear on the dashboard, and
 * `vehicle.spec.ts` asserts against a single "View Details" button and a
 * unique vehicle heading. Leaving three extra vehicles behind turned both of
 * those into strict-mode violations -- a spec this file does not touch,
 * failing because of data this file created. The backend suite hit the
 * identical problem with a paginated listing.
 */
test.afterAll(async ({ playwright }) => {
  if (vehicleVins.size === 0) return
  const admin = await adminSession()
  const context = await playwright.request.newContext({ baseURL: ROOT_BASE_URL })
  try {
    for (const vin of vehicleVins.values()) {
      await context.delete(`${API_BASE}/vehicles/${vin}`, { headers: admin.headers })
    }
  } finally {
    await context.dispose()
    vehicleVins.clear()
  }
})

test.describe('Tires', () => {
  test('create-and-mount, then dismount, keeps the tire and frees the corner', async ({
    page,
    request,
  }) => {
    const vin = await tireVehicle(request)
    const admin = await adminSession()
    // Seeded through the API so the test is about the BROWSER flow that
    // follows, not about form-filling.
    const created = await request.post(
      `${API_BASE}/vehicles/${vin}/tires/create-and-mount`,
      {
        headers: admin.headers,
        data: {
          vin,
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

    await openTires(page, vin)
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
    //
    // Scoped to THIS tire's card. `getByText('In storage').first()` happened
    // to work only because this test runs before any other tire is
    // dismounted; a reordering would have made it assert against someone
    // else's card. Order-dependent assertions are the same defect as the
    // `.first()` one below, just not yet triggered.
    const card = page.locator('.rounded-card', { hasText: 'E2E Michelin' }).first()
    await expect(card).toBeVisible({ timeout: 10000 })
    await expect(card.getByText('In storage')).toBeVisible()
    // And it can be put back on, which is the seasonal-swap case the whole
    // mount-period model exists for.
    await expect(card.getByRole('button', { name: 'Mount' })).toBeVisible()
  })

  test('a tire with no odometer bounds prompts rather than showing a zero', async ({
    page,
    request,
  }) => {
    const vin = await tireVehicle(request)
    const admin = await adminSession()
    // The upgrade-day shape: mounted, but with no odometer on the mount, so
    // there is no bounded distance. Every tire on every instance looks like
    // this the moment migration 097 runs, which is why "0 km" here would be
    // the single most visible wrong number in the release.
    const created = await request.post(
      `${API_BASE}/vehicles/${vin}/tires/create-and-mount`,
      {
        headers: admin.headers,
        data: { vin, position: 'SPARE', brand: 'E2E Unbounded', tread_depth_mm: 7 },
      }
    )
    expect([201, 409], `seed failed: ${await created.text()}`).toContain(created.status())
    test.skip(created.status() === 409, 'SPARE already occupied by a previous run')

    const body = await created.json()
    // The contract, before the browser is involved: a spare that has never
    // rolled reports its own status and no number.
    expect(body.distance_status).toBe('spare_only')
    expect(body.distance_km).toBeNull()

    await openTires(page, vin)
    await expect(page.getByText('E2E Unbounded')).toBeVisible({ timeout: 10000 })

    // BOTH directions, scoped to THIS tire's card.
    //
    // Two earlier versions of this assertion were satisfied by the wrong
    // thing. Checking only that no "0 km" appears passed while the mounted
    // card carried no distance row at all -- "no zero" is also true of
    // "nothing rendered". Adding `getByText('Distance on tire').first()` did
    // not fix it either: the previous test in this file leaves a DISMOUNTED
    // tire on the page, whose storage card has that same label, so `.first()`
    // matched a card this test is not about. Verified by mutation: deleting
    // the mounted card's distance row must fail this test.
    const card = page.locator('.rounded-card', { hasText: 'E2E Unbounded' }).first()
    await expect(card).toBeVisible({ timeout: 10000 })
    await expect(card.getByText('Distance on tire')).toBeVisible()
    // 'never rolled' only: the card ALSO renders 'Spare' as the position
    // heading, so a looser regex matches two elements and fails strict mode.
    await expect(card.getByText(/never rolled/i)).toBeVisible()
    await expect(card.getByText(/^0 (km|mi)$/)).toHaveCount(0)
  })

  test('a stale client POSTing a position is rejected loudly', async ({ request }) => {
    const vin = await tireVehicle(request)
    const admin = await adminSession()
    // The release's breaking change, asserted as a contract rather than
    // described in a changelog. A browser tab left open across the upgrade
    // sends exactly this payload; the 422 naming the field is what stops it
    // silently creating a second, unmounted tire.
    const response = await request.post(`${API_BASE}/vehicles/${vin}/tires`, {
      headers: admin.headers,
      data: { vin, position: 'FL', tread_depth_mm: 8 },
    })
    expect(response.status()).toBe(422)
    const detail = await response.text()
    expect(detail).toContain('position')
  })
})

test.describe('Tire rotation and retirement', () => {
  test('an X-pattern rotation moves every tire', async ({ request }) => {
    const vin = await tireVehicle(request, 'rotation')
    // The two-phase write, end to end. `uq_tires_vin_position` is an IMMEDIATE
    // unique index, so a naive one-at-a-time assignment collides on the first
    // move -- every destination is occupied. This is the API-level proof that
    // the vacate/flush/assign split survives a real request; the unit test
    // proves the mechanism, this proves the wiring.
    const admin = await adminSession()
    const corners = ['FL', 'FR', 'RL', 'RR'] as const
    const ids: Record<string, number> = {}

    for (const position of corners) {
      const created = await request.post(
        `${API_BASE}/vehicles/${vin}/tires/create-and-mount`,
        {
          headers: admin.headers,
          data: {
            vin,
            position,
            brand: `E2E Rot ${position}`,
            tread_depth_mm: 8,
            mounted_odometer_km: 1000,
          },
        }
      )
      if (created.status() === 409) test.skip(true, `${position} already occupied`)
      expect(created.status(), `seed ${position}: ${await created.text()}`).toBe(201)
      ids[position] = (await created.json()).id
    }

    const rotated = await request.post(`${API_BASE}/vehicles/${vin}/tires/rotate`, {
      headers: admin.headers,
      data: {
        odometer_km: 20000,
        moves: [
          { tire_id: ids.FL, position: 'RR' },
          { tire_id: ids.FR, position: 'RL' },
          { tire_id: ids.RL, position: 'FR' },
          { tire_id: ids.RR, position: 'FL' },
        ],
      },
    })
    expect(rotated.status(), await rotated.text()).toBe(200)

    const placed = Object.fromEntries(
      (await rotated.json()).tires.map((t: { id: number; position: string }) => [
        t.id,
        t.position,
      ])
    )
    expect(placed[ids.FL]).toBe('RR')
    expect(placed[ids.RR]).toBe('FL')

    // Each corner's period closed at the rotation odometer, so distance stays
    // attributable per position rather than pooled across the vehicle.
    const listed = await request.get(`${API_BASE}/vehicles/${vin}/tires`, {
      headers: admin.headers,
    })
    const moved = (await listed.json()).tires.find(
      (t: { id: number }) => t.id === ids.FL
    )
    expect(moved.mount_periods).toHaveLength(2)

    // `complete`, and getting here took a code change. This assertion read
    // `incomplete` until the rotation started publishing its odometer as a
    // reading of the vehicle: the closed FL period was bounded (1000 ->
    // 20000), but the new RR period is OPEN, an open period's upper bound is
    // the vehicle's latest OdometerRecord, and a rotation created none. So a
    // user who rotated and dutifully typed the odometer still had the all-time
    // total withheld until they went and logged the same number a second time.
    //
    // The RR leg is 0 km because the vehicle has not been driven since, which
    // is the honest reading of the recorded facts rather than a gap.
    expect(moved.distance_status).toBe('complete')
    expect(Number(moved.distance_km)).toBe(19000)
    expect(moved.blocking_period_ids).toHaveLength(0)
  })

  test('retiring keeps the history that deleting would destroy', async ({ request }) => {
    const vin = await tireVehicle(request, 'retire')
    // The distinction the release turns on. Retire and DELETE are different
    // endpoints because replacing a worn tire must not erase the readings and
    // mount periods this feature exists to collect.
    const admin = await adminSession()
    const created = await request.post(
      `${API_BASE}/vehicles/${vin}/tires/create-and-mount`,
      {
        headers: admin.headers,
        data: {
          vin,
          position: 'SPARE',
          brand: 'E2E Retire',
          tread_depth_mm: 8,
          mounted_odometer_km: 1000,
        },
      }
    )
    expect(created.status(), await created.text()).toBe(201)
    const id = (await created.json()).id

    await request.post(`${API_BASE}/vehicles/${vin}/tires/${id}/readings`, {
      headers: admin.headers,
      data: { recorded_at: '2026-03-01', tread_depth_mm: 6, odometer_km: 15000 },
    })

    const retired = await request.post(
      `${API_BASE}/vehicles/${vin}/tires/${id}/retire`,
      { headers: admin.headers, data: { dismounted_odometer_km: 20000 } }
    )
    expect(retired.status(), await retired.text()).toBe(200)
    const body = await retired.json()
    expect(body.retired_on).not.toBeNull()
    expect(body.position).toBeNull()
    // Everything survives.
    expect(body.readings.length).toBeGreaterThanOrEqual(1)
    expect(body.mount_periods).toHaveLength(1)
    expect(body.mount_periods[0].dismounted_on).not.toBeNull()

    // Out of the default listing, present when asked for. A retired tire is
    // history, not inventory -- but it is not gone.
    const listed = await request.get(`${API_BASE}/vehicles/${vin}/tires`, {
      headers: admin.headers,
    })
    const defaultIds = (await listed.json()).tires.map((t: { id: number }) => t.id)
    expect(defaultIds).not.toContain(id)

    const withRetired = await request.get(
      `${API_BASE}/vehicles/${vin}/tires?include_retired=true`,
      { headers: admin.headers }
    )
    const allIds = (await withRetired.json()).tires.map((t: { id: number }) => t.id)
    expect(allIds).toContain(id)

    // And the corner it vacated is free for the replacement.
    const replacement = await request.post(
      `${API_BASE}/vehicles/${vin}/tires/create-and-mount`,
      {
        headers: admin.headers,
        data: { vin, position: 'SPARE', brand: 'E2E Replacement', tread_depth_mm: 9 },
      }
    )
    expect(replacement.status(), await replacement.text()).toBe(201)
  })
})

/**
 * The same three operations, through the controls a user actually has.
 *
 * The block above drives rotate and retire with `request.post`, which is why
 * it stayed green while `useRotateTires`, `useRetireTire` and `useCreateTire`
 * had zero callers anywhere in `src/`: it proved the endpoints worked, not
 * that anyone could reach them. Every assertion here goes through the browser
 * for that reason.
 */
test.describe('Tire rotation and retirement, through the UI', () => {
  test('the header rotate control moves every tire', async ({ page, request }) => {
    const vin = await tireVehicle(request, 'rotate-ui')
    const admin = await adminSession()
    for (const position of ['FL', 'FR', 'RL', 'RR'] as const) {
      const created = await request.post(`${API_BASE}/vehicles/${vin}/tires/create-and-mount`, {
        headers: admin.headers,
        data: {
          vin,
          position,
          brand: `E2E RotUI ${position}`,
          tread_depth_mm: 8,
          mounted_odometer_km: 1000,
        },
      })
      expect(created.status(), `seed ${position}: ${await created.text()}`).toBe(201)
    }

    await openTires(page, vin)
    const cardFor = (brand: string) =>
      page.locator('.rounded-card', { hasText: brand }).first()
    await expect(cardFor('E2E RotUI FL')).toContainText('Front Left')

    await page.getByRole('button', { name: 'Rotate' }).click()
    const drawer = page.getByRole('dialog')
    await expect(drawer).toBeVisible({ timeout: 5000 })
    // Forward cross: the fronts go straight back, the rears cross forward.
    await drawer.getByRole('button', { name: 'Forward cross' }).click()
    await drawer.locator('#rotate-odometer').fill('20000')
    await drawer.getByRole('button', { name: 'Rotate', exact: true }).click()
    await expect(drawer).toBeHidden({ timeout: 10000 })

    // Every corner reassigned, asserted per tire rather than as a count: a
    // rotation that moved three of four and left one behind would still show
    // four cards on four corners.
    await expect(cardFor('E2E RotUI FL')).toContainText('Rear Left', { timeout: 10000 })
    await expect(cardFor('E2E RotUI FR')).toContainText('Rear Right')
    await expect(cardFor('E2E RotUI RL')).toContainText('Front Right')
    await expect(cardFor('E2E RotUI RR')).toContainText('Front Left')
  })

  test('rotate is refused, visibly, when a corner is empty', async ({ page, request }) => {
    const vin = await tireVehicle(request, 'rotate-ui-partial')
    const admin = await adminSession()
    const created = await request.post(`${API_BASE}/vehicles/${vin}/tires/create-and-mount`, {
      headers: admin.headers,
      data: { vin, position: 'FL', brand: 'E2E RotPartial', tread_depth_mm: 8 },
    })
    expect(created.status(), await created.text()).toBe(201)

    await openTires(page, vin)
    await expect(page.getByText('E2E RotPartial')).toBeVisible({ timeout: 10000 })
    // Disabled rather than allowed-and-rejected: a partial pattern comes back
    // as a 404 or a 409 naming a corner, neither of which tells the user that
    // what they actually need is a fourth tire.
    await expect(page.getByRole('button', { name: 'Rotate' })).toBeDisabled()
  })

  test('retiring is reachable from the card, and keeps the tire out of the list', async ({
    page,
    request,
  }) => {
    const vin = await tireVehicle(request, 'retire-ui')
    const admin = await adminSession()
    const created = await request.post(`${API_BASE}/vehicles/${vin}/tires/create-and-mount`, {
      headers: admin.headers,
      data: {
        vin,
        position: 'RL',
        brand: 'E2E RetireUI',
        tread_depth_mm: 8,
        mounted_odometer_km: 1000,
      },
    })
    expect(created.status(), await created.text()).toBe(201)

    await openTires(page, vin)
    const card = page.locator('.rounded-card', { hasText: 'E2E RetireUI' }).first()
    await expect(card).toBeVisible({ timeout: 10000 })

    await card.getByRole('button', { name: 'Retire' }).click()
    const drawer = page.getByRole('dialog')
    await expect(drawer).toBeVisible({ timeout: 5000 })
    await drawer.locator('#retire-odometer').fill('30000')
    await drawer.getByRole('button', { name: 'Retire', exact: true }).click()

    // Gone from the list, and its corner is free again for the replacement.
    await expect(page.getByText('E2E RetireUI')).toBeHidden({ timeout: 10000 })
    const listed = await request.get(
      `${API_BASE}/vehicles/${vin}/tires?include_retired=true`,
      { headers: admin.headers }
    )
    const retired = (await listed.json()).tires.filter(
      (t: { brand: string; retired_on: string | null }) => t.brand === 'E2E RetireUI'
    )
    // The point of retire over delete: the tire and its history are still
    // there, they are just no longer inventory.
    expect(retired).toHaveLength(1)
    expect(retired[0].retired_on).not.toBeNull()
    expect(retired[0].mount_periods.length).toBeGreaterThanOrEqual(1)
  })

  test('a tire can be entered straight into storage', async ({ page, request }) => {
    const vin = await tireVehicle(request, 'storage-ui')
    await openTires(page, vin)

    await page.getByRole('button', { name: 'Add Tire' }).click()
    const drawer = page.getByRole('dialog')
    await expect(drawer).toBeVisible({ timeout: 5000 })
    await drawer.getByRole('button', { name: 'In storage' }).click()
    await drawer.getByLabel('Brand').fill('E2E StoredSet')
    await drawer.getByRole('button', { name: 'Save' }).click()
    await expect(drawer).toBeHidden({ timeout: 10000 })

    // Under the storage heading, with a Mount button: a tire you own and have
    // not fitted. Before this there was no way to enter one without mounting
    // it onto a corner first and dismounting it again.
    const card = page.locator('.rounded-card', { hasText: 'E2E StoredSet' }).first()
    await expect(card).toBeVisible({ timeout: 10000 })
    await expect(card.getByRole('button', { name: 'Mount' })).toBeVisible()
  })
})
