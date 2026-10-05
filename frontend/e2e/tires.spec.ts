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
          // Explicit past date: this spec is about the dismount flow, not
          // about whether the server's default "today" matches the browser's
          // (that contract has its own spec, household-timezone.spec.ts).
          mounted_on: '2026-04-01',
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
    //
    // `exact: true`: v3.4.0 added a second "In storage since <date>" line to
    // the same card (the in-storage-since summary), and a loose substring
    // match now resolves to both, a strict-mode violation this task's first
    // real Playwright run against the full suite is what caught.
    const card = page.locator('.rounded-card', { hasText: 'E2E Michelin' }).first()
    await expect(card).toBeVisible({ timeout: 10000 })
    await expect(card.getByText('In storage', { exact: true })).toBeVisible()
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

  test('a tire added at a corner takes a backdated date and the suggested odometer', async ({
    page,
    request,
  }) => {
    const vin = await tireVehicle(request, 'add-dated')
    const admin = await adminSession()
    const seeded = await request.post(`${API_BASE}/vehicles/${vin}/odometer`, {
      headers: admin.headers,
      data: { vin, date: '2026-04-01', odometer_km: 100000 },
    })
    expect(seeded.status(), await seeded.text()).toBe(201)

    await openTires(page, vin)
    await page.getByRole('button', { name: 'Add Tire' }).click()
    const drawer = page.getByRole('dialog')
    await drawer.getByRole('button', { name: 'FL', exact: true }).click()
    await drawer.getByLabel('Brand').fill('E2E Dated')
    await drawer.locator('#tire-mount-date').fill('2026-04-10')
    // The suggestion names the reading's own date, so the user can judge it.
    await expect(drawer.getByText(/Nearest reading/)).toBeVisible({ timeout: 5000 })
    await drawer.getByRole('button', { name: 'Use' }).click()
    await expect(drawer.locator('#tire-mount-odometer')).toHaveValue(/100000|62137/)
    await drawer.getByRole('button', { name: 'Save' }).click()
    await expect(drawer).toBeHidden({ timeout: 10000 })

    const card = page.locator('.rounded-card', { hasText: 'E2E Dated' }).first()
    await expect(card).toBeVisible({ timeout: 10000 })
    await expect(card.getByText('Mounted', { exact: true })).toBeVisible()
    await expect(card.getByText(/Not yet known/)).toHaveCount(0)

    // The contract, from the API: the period is bounded and dated as typed.
    const listed = await request.get(`${API_BASE}/vehicles/${vin}/tires`, { headers: admin.headers })
    const tire = (await listed.json()).tires.find((t: { brand: string }) => t.brand === 'E2E Dated')
    expect(tire.mount_periods[0].mounted_on).toBe('2026-04-10')
    expect(Number(tire.mount_periods[0].mounted_odometer_km)).toBe(100000)
  })

  test('Fix opens the history, and supplying the mount odometer fills the distance in', async ({
    page,
    request,
  }) => {
    const vin = await tireVehicle(request, 'fix-ui')
    const admin = await adminSession()
    // The upgrade-day shape: mounted with no odometer on the mount.
    const created = await request.post(`${API_BASE}/vehicles/${vin}/tires/create-and-mount`, {
      headers: admin.headers,
      data: { vin, position: 'RL', brand: 'E2E Fixable', tread_depth_mm: 7, mounted_on: '2026-04-01' },
    })
    expect(created.status(), await created.text()).toBe(201)
    // A later vehicle reading, so a bounded period has a distance to show.
    const later = await request.post(`${API_BASE}/vehicles/${vin}/odometer`, {
      headers: admin.headers,
      data: { vin, date: '2026-05-01', odometer_km: 101000 },
    })
    expect(later.status(), await later.text()).toBe(201)

    await openTires(page, vin)
    const card = page.locator('.rounded-card', { hasText: 'E2E Fixable' }).first()
    await expect(card.getByText(/Not yet known/)).toBeVisible({ timeout: 10000 })
    await card.getByRole('button', { name: 'Fix' }).click()

    const history = page.getByRole('dialog').first()
    await expect(history.getByText('Needs an odometer')).toBeVisible({ timeout: 5000 })
    await history.getByRole('button', { name: 'Edit' }).first().click()
    // Named, not `.last()`: the history drawer stays open behind the nested
    // editor, so once the editor closes on save, `.last()` re-resolves to the
    // still-open history dialog and `toBeHidden` never observes it -- a
    // locator that silently retargets rather than a save that fails to close.
    const editor = page.getByRole('dialog', { name: /Edit mount period/ })
    await editor.locator('#period-mount-odometer').fill('100500')
    await editor.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(editor).toBeHidden({ timeout: 10000 })

    await expect(card.getByText(/Not yet known/)).toHaveCount(0, { timeout: 10000 })
    await expect(card.getByRole('button', { name: 'Fix' })).toHaveCount(0)
  })

  test('a reading with a mistyped odometer is named by the refusal and deleted from the history', async ({
    page,
    request,
  }) => {
    const vin = await tireVehicle(request, 'reading-delete')
    const admin = await adminSession()
    // Pinned rather than assumed: the refusal names the reading's odometer in
    // the account's resolved unit, and imperial is this suite's steady state
    // (settings.spec.ts restores it there), so nothing needs restoring after.
    const units = await request.put(`${API_BASE}/auth/me/units`, {
      data: { unit_preference: 'imperial' },
      headers: admin.headers,
    })
    expect(units.ok(), `pin to imperial failed: ${units.status()} ${await units.text()}`).toBeTruthy()

    const created = await request.post(`${API_BASE}/vehicles/${vin}/tires/create-and-mount`, {
      headers: admin.headers,
      data: {
        vin,
        position: 'FL',
        brand: 'E2E Typo',
        tread_depth_mm: 8,
        mounted_on: '2026-01-01',
        mounted_odometer_km: 10000,
      },
    })
    expect(created.status(), await created.text()).toBe(201)
    const tireId = (await created.json()).id
    // 150,000 typed for 15,000. Log Reading accepts it: readings are not
    // validated against the mount history, the writers that change it are.
    const typo = await request.post(`${API_BASE}/vehicles/${vin}/tires/${tireId}/readings`, {
      headers: admin.headers,
      data: { recorded_at: '2026-03-01', tread_depth_mm: 7, odometer_km: 150000 },
    })
    expect(typo.status(), await typo.text()).toBe(201)

    await openTires(page, vin)
    const card = page.locator('.rounded-card', { hasText: 'E2E Typo' }).first()
    await expect(card).toBeVisible({ timeout: 10000 })

    // An honest dismount, today, at an odometer (in miles, the pinned unit)
    // between the mount and the typo. Refused, and the sentence says which
    // reading.
    const dismount = async () => {
      await card.getByRole('button', { name: 'Dismount' }).click()
      const drawer = page.getByRole('dialog')
      await drawer.locator('#dismount-odometer').fill('20000')
      await drawer.getByRole('button', { name: 'Dismount', exact: true }).click()
      return drawer
    }
    const refusedDrawer = await dismount()
    // The reading's odometer was seeded directly in km through the API
    // (150,000), so the refusal names it in the account's pinned unit. The
    // server's message formatter (`distance_formatter` in tire_history.py)
    // keeps one decimal place, unlike the frontend's whole-mile display:
    // 150000 / 1.609344 = 93205.678..., quantized to 93,205.7 mi.
    await expect(
      page.getByText('contradicts the reading dated 2026-03-01 at 93,205.7 mi')
    ).toBeVisible({
      timeout: 10000,
    })
    // The toast has to clear the drawer's footer. When toasts sat bottom-right
    // this one covered Cancel, and the mouse resting on it paused the dismiss
    // timer, so the click below waited out the 4s timer at best and timed out
    // at worst. Checked again at 720px, where this 440px drawer reaches under
    // the toast's left corner too, so bottom-left alone would still cover it.
    const toastClearsFooter = async (): Promise<void> => {
      // Wait out the slide-in. Mid-animation the toast is half off-screen and
      // clears the footer whichever corner it is headed for.
      const toast = page.locator('[data-sonner-toast]').first()
      await expect(toast).toBeInViewport({ ratio: 1 })
      const t = await toast.boundingBox()
      const f = await refusedDrawer.locator('footer').boundingBox()
      expect(t && f, 'toast and footer both laid out').toBeTruthy()
      const overlaps =
        t!.x < f!.x + f!.width && t!.x + t!.width > f!.x && t!.y < f!.y + f!.height && t!.y + t!.height > f!.y
      expect(overlaps, `toast ${JSON.stringify(t)} over footer ${JSON.stringify(f)}`).toBe(false)
    }
    await toastClearsFooter()
    const viewport = page.viewportSize()!
    await page.setViewportSize({ width: 720, height: viewport.height })
    await toastClearsFooter()
    await page.setViewportSize(viewport)
    await refusedDrawer.getByRole('button', { name: 'Cancel' }).click()
    await expect(refusedDrawer).toBeHidden({ timeout: 10000 })

    // The repair: the tire's history, Delete on that reading, confirmed. The
    // card's own text opens it now; the named history button only shows on
    // keyboard focus, so Playwright can't click it (#179).
    await card.getByText('E2E Typo', { exact: true }).click()
    const history = page.getByRole('dialog')
    const confirmed = new Promise<string>((resolve) => {
      page.once('dialog', async (dialog) => {
        const message = dialog.message()
        await dialog.accept()
        resolve(message)
      })
    })
    await history.getByRole('button', { name: /^Delete the reading of / }).click()
    expect(await confirmed).toMatch(/^Delete the reading of /)
    await expect(history.getByText('No readings logged yet')).toBeVisible({ timeout: 10000 })
    await history.getByRole('button', { name: 'Close' }).first().click()
    await expect(history).toBeHidden({ timeout: 10000 })

    const acceptedDrawer = await dismount()
    await expect(acceptedDrawer).toBeHidden({ timeout: 10000 })
    await expect(card.getByText('In storage', { exact: true })).toBeVisible({ timeout: 10000 })

    const listed = await request.get(`${API_BASE}/vehicles/${vin}/tires`, { headers: admin.headers })
    const tire = (await listed.json()).tires.find((t: { id: number }) => t.id === tireId)
    expect(tire.readings).toHaveLength(0)
    expect(tire.position).toBeNull()
    expect(tire.mount_periods).toHaveLength(1)
    expect(tire.mount_periods[0].dismounted_on).not.toBeNull()
  })

  test('a past period is recorded from the history drawer, closed, and does not move the current mount', async ({
    page,
    request,
  }) => {
    const vin = await tireVehicle(request, 'past-period')
    const admin = await adminSession()
    // Mounted at FL today. The past period records this SAME tire on a
    // different corner before that, which is legal as long as the two date
    // ranges do not overlap.
    const created = await request.post(`${API_BASE}/vehicles/${vin}/tires/create-and-mount`, {
      headers: admin.headers,
      data: { vin, position: 'FL', brand: 'E2E PastPeriod', tread_depth_mm: 8 },
    })
    expect([201, 409], `seed failed: ${await created.text()}`).toContain(created.status())
    test.skip(created.status() === 409, 'FL already occupied by a previous run')
    const tireId = (await created.json()).id

    const monthsAgo = (months: number): string => {
      const date = new Date()
      date.setMonth(date.getMonth() - months)
      return date.toISOString().slice(0, 10)
    }
    const mountedOn = monthsAgo(12)
    const dismountedOn = monthsAgo(11)

    await openTires(page, vin)
    const card = page.locator('.rounded-card', { hasText: 'E2E PastPeriod' }).first()
    await expect(card).toBeVisible({ timeout: 10000 })
    // A click on the card's text, the way a person opens it (#179).
    await card.getByText('E2E PastPeriod', { exact: true }).click()
    const history = page.getByRole('dialog').first()
    await expect(history).toBeVisible({ timeout: 5000 })

    await history.getByRole('button', { name: 'Add past period' }).click()
    const addDrawer = page.getByRole('dialog', { name: 'Add a past period' })
    await expect(addDrawer).toBeVisible({ timeout: 5000 })
    await addDrawer.getByRole('button', { name: 'Front Right', exact: true }).click()
    await addDrawer.locator('#past-mount-date').fill(mountedOn)
    await addDrawer.locator('#past-dismount-date').fill(dismountedOn)
    await addDrawer.locator('#past-mount-odometer').fill('5000')
    await addDrawer.locator('#past-dismount-odometer').fill('8000')
    await addDrawer.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(addDrawer).toBeHidden({ timeout: 10000 })

    // The new period is on the history list, labelled by its OWN corner
    // rather than the tire's current one.
    await expect(history.getByText('Front Right')).toBeVisible({ timeout: 10000 })

    const listed = await request.get(`${API_BASE}/vehicles/${vin}/tires`, { headers: admin.headers })
    const tire = (await listed.json()).tires.find((t: { id: number }) => t.id === tireId)
    const pastPeriod = tire.mount_periods.find((p: { position: string }) => p.position === 'FR')
    expect(pastPeriod, JSON.stringify(tire.mount_periods)).toBeTruthy()
    expect(pastPeriod.mounted_on).toBe(mountedOn)
    expect(pastPeriod.dismounted_on).toBe(dismountedOn)
    // The past period is closed and the tire's CURRENT mount is untouched.
    expect(tire.position).toBe('FL')
  })

  test('a contradiction is badged and explained, and clears when the reading is deleted', async ({
    page,
    request,
  }) => {
    const vin = await tireVehicle(request, 'contradiction-ui')
    const admin = await adminSession()
    // Pinned rather than assumed: the fault names the reading's odometer in
    // the account's resolved unit, and imperial is this suite's steady state
    // (settings.spec.ts restores it there), so nothing needs restoring after.
    const units = await request.put(`${API_BASE}/auth/me/units`, {
      data: { unit_preference: 'imperial' },
      headers: admin.headers,
    })
    expect(units.ok(), `pin to imperial failed: ${units.status()} ${await units.text()}`).toBeTruthy()

    const created = await request.post(`${API_BASE}/vehicles/${vin}/tires/create-and-mount`, {
      headers: admin.headers,
      data: {
        vin,
        position: 'RR',
        brand: 'E2E Contradiction',
        tread_depth_mm: 8,
        mounted_on: '2026-01-01',
        mounted_odometer_km: 10000,
      },
    })
    expect([201, 409], `seed failed: ${await created.text()}`).toContain(created.status())
    test.skip(created.status() === 409, 'RR already occupied by a previous run')
    const tireId = (await created.json()).id

    const dismounted = await request.post(`${API_BASE}/vehicles/${vin}/tires/${tireId}/dismount`, {
      headers: admin.headers,
      data: { dismounted_on: '2026-03-02', dismounted_odometer_km: 15000 },
    })
    expect(dismounted.status(), await dismounted.text()).toBe(200)

    // Between the mount and the dismount, at an odometer ABOVE the dismount:
    // a real contradiction (the vehicle's odometer would have to run
    // backwards), which the reading endpoint does not refuse -- only the
    // writers that change the mount history do.
    const reading = await request.post(`${API_BASE}/vehicles/${vin}/tires/${tireId}/readings`, {
      headers: admin.headers,
      data: { recorded_at: '2026-02-01', tread_depth_mm: 7, odometer_km: 20000 },
    })
    expect(reading.status(), await reading.text()).toBe(201)

    await openTires(page, vin)
    const card = page.locator('.rounded-card', { hasText: 'E2E Contradiction' }).first()
    await expect(card).toBeVisible({ timeout: 10000 })
    await card.getByRole('button', { name: 'History', exact: true }).click()
    const history = page.getByRole('dialog')
    await expect(history).toBeVisible({ timeout: 5000 })

    await expect(history.getByText('Check this period')).toBeVisible({ timeout: 10000 })
    // The reading's odometer was seeded directly in km through the API
    // (20,000), so the fault names it in the account's pinned unit. The
    // server's message formatter keeps one decimal place, unlike the
    // frontend's whole-mile display: 20000 / 1.609344 = 12427.423...,
    // quantized to 12,427.4 mi.
    await expect(
      history.getByText('contradicts the reading dated 2026-02-01 at 12,427.4 mi')
    ).toBeVisible({ timeout: 10000 })

    const confirmed = new Promise<string>((resolve) => {
      page.once('dialog', async (dialog) => {
        const message = dialog.message()
        await dialog.accept()
        resolve(message)
      })
    })
    await history.getByRole('button', { name: /^Delete the reading of / }).click()
    expect(await confirmed).toMatch(/^Delete the reading of /)

    await expect(history.getByText('No readings logged yet')).toBeVisible({ timeout: 10000 })
    await expect(history.getByText('Check this period')).toHaveCount(0)
    await expect(history.getByText(/contradicts the reading dated/)).toHaveCount(0)
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
            // Past date for the same reason as the dismount seed above.
            mounted_on: '2026-04-01',
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
          // Explicit and before the reading below. Omitting this defaults
          // `mounted_on` to today (TireService.create_and_mount), which put
          // the mount AFTER the reading dated in the past and tripped this
          // release's own period-contradiction validation (142c42f, 4a66146)
          // -- correctly, since that reading's odometer (15000) is ABOVE the
          // mount odometer (1000): the vehicle's odometer would have run
          // backwards between the reading and the mount. A reading taken
          // before mounting is legal in itself (a stored tire measured on the
          // shelf); only one above the mount odometer contradicts it. First
          // caught by this task's full Playwright run.
          mounted_on: '2026-01-01',
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
        // Past date for the same reason as the dismount seed above.
        mounted_on: '2026-04-01',
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

    // The way back. Retired tires are hidden until asked for, then restorable.
    await page.getByLabel('Show retired').click()
    const retiredCard = page.locator('.rounded-card', { hasText: 'E2E RetireUI' }).first()
    await expect(retiredCard).toBeVisible({ timeout: 10000 })
    await expect(retiredCard.getByText(/^Retired /)).toBeVisible()
    await retiredCard.getByRole('button', { name: 'Restore' }).click()
    // Back in storage: a Mount button, no Restore.
    await expect(retiredCard.getByRole('button', { name: 'Mount' })).toBeVisible({ timeout: 10000 })
    await expect(retiredCard.getByRole('button', { name: 'Restore' })).toHaveCount(0)
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

/**
 * Tire sets, end to end.
 *
 * The set table and `tires.set_id` shipped with migration 097 and then sat
 * unused for the same reason rotate and retire did: no schema, no route, no
 * control. This drives the whole loop through the browser -- name a set, file
 * tires into it, fit it -- because that is the only kind of test that would
 * have noticed.
 */
test.describe('Tire sets', () => {
  test('a seasonal set is named, filled and fitted', async ({ page, request }) => {
    const vin = await tireVehicle(request, 'sets-ui')
    const admin = await adminSession()

    // Two tires with a history at RL and RR, then taken off. The corners they
    // remember are what the fit reads back, and seeding that through the API
    // keeps this test about the SET flow rather than about mount forms.
    for (const position of ['RL', 'RR'] as const) {
      const created = await request.post(`${API_BASE}/vehicles/${vin}/tires/create-and-mount`, {
        headers: admin.headers,
        data: {
          vin,
          position,
          brand: `E2E Set ${position}`,
          tread_depth_mm: 8,
          mounted_odometer_km: 1000,
        },
      })
      expect(created.status(), `seed ${position}: ${await created.text()}`).toBe(201)
      const off = await request.post(
        `${API_BASE}/vehicles/${vin}/tires/${(await created.json()).id}/dismount`,
        { headers: admin.headers, data: { dismounted_odometer_km: 20000 } }
      )
      expect(off.status(), await off.text()).toBe(200)
    }

    await openTires(page, vin)
    await expect(page.getByText('E2E Set RL')).toBeVisible({ timeout: 10000 })

    // Name the set.
    await page.getByRole('button', { name: 'Sets' }).click()
    let drawer = page.getByRole('dialog')
    await expect(drawer).toBeVisible({ timeout: 5000 })
    await drawer.locator('#new-set-name').fill('E2E Winter')
    await drawer.getByRole('button', { name: 'Add set' }).click()
    await expect(drawer.getByText('E2E Winter')).toBeVisible({ timeout: 10000 })
    await drawer.getByRole('button', { name: 'Close' }).last().click()
    await expect(drawer).toBeHidden({ timeout: 10000 })

    // File both tires into it, from each tire's own edit drawer.
    for (const brand of ['E2E Set RL', 'E2E Set RR']) {
      const card = page.locator('.rounded-card', { hasText: brand }).first()
      await card.getByRole('button', { name: 'Edit' }).click()
      drawer = page.getByRole('dialog')
      await expect(drawer).toBeVisible({ timeout: 5000 })
      await drawer.getByRole('button', { name: 'E2E Winter' }).click()
      await drawer.getByRole('button', { name: 'Save' }).click()
      await expect(drawer).toBeHidden({ timeout: 10000 })
    }

    // Fit it: one action, and neither corner is typed anywhere.
    await page.getByRole('button', { name: 'Sets' }).click()
    drawer = page.getByRole('dialog')
    await expect(drawer.getByText('Tires: 2 · Fitted: 0')).toBeVisible({ timeout: 10000 })
    await drawer.getByRole('button', { name: 'Fit', exact: true }).click()
    await drawer.locator('input[id^="set-fit-"][id$="-odometer"]').fill('30000')
    await drawer.getByRole('button', { name: 'Fit', exact: true }).last().click()
    await expect(drawer).toBeHidden({ timeout: 10000 })

    // Each tire back on the corner it remembered.
    await expect(
      page.locator('.rounded-card', { hasText: 'E2E Set RL' }).first()
    ).toContainText('Rear Left', { timeout: 10000 })
    await expect(
      page.locator('.rounded-card', { hasText: 'E2E Set RR' }).first()
    ).toContainText('Rear Right')
  })

  test('a set that has never been fitted says so instead of guessing', async ({
    page,
    request,
  }) => {
    const vin = await tireVehicle(request, 'sets-ui-fresh')
    const admin = await adminSession()
    // Straight into storage: no mount history, so no corner to put it back on.
    const created = await request.post(`${API_BASE}/vehicles/${vin}/tires`, {
      headers: admin.headers,
      data: { vin, brand: 'E2E NeverFitted', tread_depth_mm: 8 },
    })
    expect(created.status(), await created.text()).toBe(201)
    const set = await request.post(`${API_BASE}/vehicles/${vin}/tire-sets`, {
      headers: admin.headers,
      data: { name: 'E2E Fresh' },
    })
    expect(set.status(), await set.text()).toBe(201)
    const assigned = await request.put(
      `${API_BASE}/vehicles/${vin}/tires/${(await created.json()).id}`,
      { headers: admin.headers, data: { set_id: (await set.json()).id } }
    )
    expect(assigned.status(), await assigned.text()).toBe(200)

    await openTires(page, vin)
    await page.getByRole('button', { name: 'Sets' }).click()
    const drawer = page.getByRole('dialog')
    await drawer.getByRole('button', { name: 'Fit', exact: true }).click()
    await drawer.locator('input[id^="set-fit-"][id$="-odometer"]').fill('30000')
    await drawer.getByRole('button', { name: 'Fit', exact: true }).last().click()

    // Named, and nothing moves. Guessing a corner would put a tire somewhere
    // the user did not choose; doing three of four would leave an arrangement
    // nobody asked for.
    await expect(page.getByText(/E2E NeverFitted/)).toBeVisible({ timeout: 10000 })
    await expect(drawer).toBeVisible()
  })
})
