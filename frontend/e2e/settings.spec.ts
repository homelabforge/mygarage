import { type Page, type Response, request as apiRequest } from '@playwright/test'

import { test, expect } from './helpers/fixtures'
import { adminSessionFromStorageState, type AdminSession } from './helpers/seed'
import { TEST_VEHICLE } from './helpers/selectors'

/**
 * Settings, and the units flow issue #152 reported.
 *
 * ★ THIS FILE IS THE ONLY PLACE THE UNITS FLOW IS DRIVEN IN A REAL BROWSER, and
 * that is why it exists rather than one more vitest file. `@/services/api` is
 * mocked in the unit suite, so a mock accepts any body at any URL. Two live
 * regressions shipped behind a green suite for exactly that reason:
 *
 *   1. the units card sent `PUT /auth/me`, a route that stopped accepting
 *      `unit_preference` (spec D9b), so every preset click was a 422 that
 *      toasted an error and reverted;
 *   2. a client with no account had its choice written to the legacy
 *      `unit_preference` localStorage key, which `utils/unitPrefsStore.ts`
 *      ignores once its own key exists, so the anonymous control changed
 *      nothing at all.
 *
 * Neither is visible to a mocked suite. Both are asserted below: the first by
 * reading the real response off the wire, the second by reading the key the
 * store actually owns.
 *
 * ★ EVERY UNITS TEST STARTS FROM METRIC, DELIBERATELY. The imperial preset
 * already resolves pressure to `psi` (`types/units.ts`), so "the card reads
 * PSI" is true at t=0 for a freshly seeded account and would prove nothing.
 * Metric resolves pressure to `kpa`, so PSI is a real state change that the
 * flow has to produce.
 */

// The root project's baseURL, spelled out because `test.beforeAll` hooks run
// without the test-scoped `request` fixture and have to build their own
// context. Matches `playwright.config.ts`'s root `use.baseURL`.
const ROOT_BASE_URL = 'http://localhost:3000'
const API_BASE = `${ROOT_BASE_URL}/api`

/** The dedicated unit mutation, the only route allowed to carry a unit set. */
const UNITS_ROUTE = /\/api\/auth\/me\/units$/

/**
 * Either self-update route, so a write to the WRONG one is caught as a failed
 * assertion rather than as a `waitForResponse` timeout.
 *
 * A timeout would prove only that nothing arrived, which is the same thing a
 * broken selector proves. Matching both routes means regression (1) above shows
 * up as "expected /api/auth/me to match /units", naming what actually happened.
 */
const SELF_UPDATE_ROUTE = /\/api\/auth\/me(\/units)?$/

/**
 * Wait for the next self-update the units card makes, whichever route it picks.
 *
 * @param page The page under test.
 * @returns The response, once it lands.
 */
function waitForUnitWrite(page: Page): Promise<Response> {
  return page.waitForResponse(
    (response) =>
      response.request().method() === 'PUT' &&
      SELF_UPDATE_ROUTE.test(new URL(response.url()).pathname),
    { timeout: 15000 },
  )
}

/**
 * Assert one units write went to the dedicated route and was accepted.
 *
 * @param pending A `waitForUnitWrite` promise armed before the click.
 */
async function expectUnitWriteAccepted(pending: Promise<Response>): Promise<void> {
  const response = await pending
  const pathname = new URL(response.url()).pathname
  expect(pathname, 'units must be written through the dedicated mutation (D9b)').toMatch(
    UNITS_ROUTE,
  )
  expect(response.status(), `${pathname} rejected the body: ${await response.text()}`).toBe(200)
}

/**
 * The storageState the setup project wrote, which this file borrows API
 * credentials from rather than logging in for itself.
 *
 * Mirrors `global.setup.ts`'s `AUTH_FILE`. Logging in here instead cost two of
 * the five auth attempts a minute the backend allows and 429'd every test in
 * this file in the full-suite run, while passing when the file was run alone.
 */
const AUTH_FILE = './e2e/.auth/user.json'

/** The admin session, resolved once for this file. */
let cachedAdmin: AdminSession | null = null

/**
 * The shared admin session, fetched on first use.
 *
 * Held in a module variable rather than a fixture because `test.beforeAll`
 * hooks get no test-scoped fixtures, and the `auth_mode` block below needs
 * credentials from exactly there.
 *
 * @returns The shared admin session.
 */
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
 * The client's own units card, as distinct from the instance-default card.
 *
 * Both render the identical Imperial / Metric / Custom controls, so every
 * assertion has to say which one it means.
 *
 * @param page The page under test.
 * @returns The region locator.
 */
function unitsCard(page: Page) {
  return page.getByRole('region', { name: 'Unit System' })
}

/**
 * The sentence naming the units this client actually resolves to.
 *
 * Anchored on the sentence's own opening so it cannot match an ancestor, and
 * targeted rather than asserting against the whole card: the Custom grid's
 * `<option>` labels contain every unit symbol in the vocabulary, so a card-wide
 * text assertion would pass while the card said the opposite.
 *
 * @param page The page under test.
 * @returns The paragraph locator.
 */
function resolvedSentence(page: Page) {
  return unitsCard(page).getByText(/^Using these units:/)
}

test.describe('Settings', () => {
  test('settings page loads', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByRole('heading', { name: /settings/i })).toBeVisible({
      timeout: 15000,
    })
  })

  // The light/dark theme control moved out of Settings into the top-bar
  // toggle (an IconButton labelled "Toggle theme"), so assert it there.
  test('theme toggle is available in the top bar', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByRole('button', { name: 'Toggle theme' })).toBeVisible({ timeout: 15000 })
  })
})

test.describe('Settings: units (authenticated)', () => {
  let admin: AdminSession

  test.beforeEach(async ({ request }) => {
    admin = await adminSession()
    // Metric, not "whatever the last test left": these specs run against a warm
    // database (`webServer.reuseExistingServer`), so the starting units are
    // arranged rather than assumed.
    const reset = await request.put(`${API_BASE}/auth/me/units`, {
      data: { unit_preference: 'metric', show_both_units: false },
      headers: admin.headers,
    })
    expect(
      reset.ok(),
      `Reset to metric failed: ${reset.status()} ${await reset.text()}`,
    ).toBeTruthy()
    // The setup is asserted, not just performed. A silently rejected reset
    // would leave the account on imperial, where `psi` is already the resolved
    // pressure and every assertion below would pass for the wrong reason.
    const account = await reset.json()
    expect(account.resolved_units.pressure, 'the reset must leave pressure on kPa').toBe('kpa')
  })

  test.afterAll(async () => {
    // Put the account back where `global.setup.ts` leaves it, so the specs that
    // sort after this file see the units a freshly seeded admin has.
    const session = await adminSession()
    const context = await apiRequest.newContext({ baseURL: ROOT_BASE_URL })
    try {
      const restored = await context.put(`${API_BASE}/auth/me/units`, {
        data: { unit_preference: 'imperial' },
        headers: session.headers,
      })
      expect(
        restored.ok(),
        `Restore to imperial failed: ${restored.status()}`,
      ).toBeTruthy()
    } finally {
      await context.dispose()
    }
  })

  test('a preset click is accepted by the dedicated units route', async ({ page }) => {
    await page.goto('/settings')
    const units = unitsCard(page)
    await expect(units).toBeVisible({ timeout: 15000 })
    await expect(units.getByRole('button', { name: 'Metric', exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
    )

    // Choosing a preset clears all eleven override columns, so it is confirmed
    // first (`UnitSetEditor`); the request goes out on the confirmation.
    await units.getByRole('button', { name: 'Imperial', exact: true }).click()
    const write = waitForUnitWrite(page)
    await units.getByRole('button', { name: 'Switch units' }).click()
    await expectUnitWriteAccepted(write)

    // The user-visible half of the same fact: a 422 puts up the error toast and
    // reverts the highlight.
    await expect(page.getByText('Unit preference saved!').first()).toBeVisible({ timeout: 10000 })
    await expect(units.getByRole('button', { name: 'Imperial', exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await expect(resolvedSentence(page)).toContainText(', PSI,')
  })

  test('a custom per-quantity set survives a reload', async ({ page }) => {
    await page.goto('/settings')
    const units = unitsCard(page)
    await expect(units).toBeVisible({ timeout: 15000 })
    // Precondition, not proof: the grid is hidden while the account is on a
    // preset, so the assertions after the reload describe a state this test
    // created rather than one it was handed.
    await expect(page.locator('#unit-pressure')).toHaveCount(0)

    const openCustom = waitForUnitWrite(page)
    await units.getByRole('button', { name: 'Custom', exact: true }).click()
    await expectUnitWriteAccepted(openCustom)

    const choosePsi = waitForUnitWrite(page)
    await page.selectOption('#unit-pressure', 'psi')
    await expectUnitWriteAccepted(choosePsi)

    // The reload is the point. It proves the write reached the database AND
    // that `resolved_units` came back on `/auth/me`: the optimistic overlay the
    // card holds while saving does not survive a navigation.
    await page.reload()
    await expect(units.getByRole('button', { name: 'Custom', exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
      { timeout: 15000 },
    )
    await expect(page.locator('#unit-pressure')).toHaveValue('psi')
    // The whole resolved set, so a change that moved more than pressure fails
    // here rather than passing as "still PSI".
    await expect(resolvedSentence(page)).toHaveText(
      'Using these units: km, km/h, m, L, L/100km, PSI, °C, kg, Nm, mm',
    )
  })

  test('issue #152: Custom pressure in PSI reads back as PSI on the tire card', async ({
    page,
    request,
  }) => {
    // Seeded canonically (kPa, mm) so the browser is the only thing that
    // converts.
    //
    // v3.3.0: `POST /tires` no longer takes a position and no longer upserts
    // by one -- a tire is a thing you own, and mounting is a separate
    // operation. Seeding goes through create-and-mount, which is atomic. A
    // re-run no longer resets the corner, so the seed tolerates the 409 it
    // gets when FL is already occupied from a previous run.
    const seeded = await request.post(
      `${API_BASE}/vehicles/${TEST_VEHICLE.vin}/tires/create-and-mount`,
      {
        headers: admin.headers,
        data: {
          vin: TEST_VEHICLE.vin,
          position: 'FL',
          tread_depth_mm: 8,
          pressure_kpa: 200,
          min_tread_mm: 2,
        },
      }
    )
    expect(
      [201, 409],
      `Seed tire failed: ${await seeded.text()}`
    ).toContain(seeded.status())

    // 1. Set Custom, with pressure on PSI.
    await page.goto('/settings')
    const units = unitsCard(page)
    await expect(units).toBeVisible({ timeout: 15000 })
    const openCustom = waitForUnitWrite(page)
    await units.getByRole('button', { name: 'Custom', exact: true }).click()
    await expectUnitWriteAccepted(openCustom)
    const choosePsi = waitForUnitWrite(page)
    await page.selectOption('#unit-pressure', 'psi')
    await expectUnitWriteAccepted(choosePsi)

    // 2. Record a tire reading.
    await page.goto(`/vehicles/${TEST_VEHICLE.vin}?tab=tires`)
    await expect(page.getByRole('heading', { name: 'Tires', exact: true })).toBeVisible({
      timeout: 15000,
    })
    await page.getByRole('button', { name: 'Log Reading' }).click()
    const drawer = page.getByRole('dialog', { name: 'Log Reading (Front Left)' })
    await expect(drawer).toBeVisible({ timeout: 10000 })
    // Entry and display must name the same unit (spec D2), so the field the
    // user types into is part of the claim, not just the card.
    await expect(page.locator('label[for="reading-pressure"]')).toHaveText('Pressure (PSI)')
    await page.locator('#reading-pressure').fill('35')

    const posted = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' && /\/tires\/\d+\/readings$/.test(response.url()),
      { timeout: 15000 },
    )
    await drawer.getByRole('button', { name: 'Save', exact: true }).click()
    expect((await posted).status(), 'the reading must be accepted').toBe(201)

    // 3. Read PSI back on the card. This is the literal reproduction of #152.
    await expect(page.getByText('35.0 PSI', { exact: true })).toBeVisible({ timeout: 10000 })

    // 4. And the number behind it is canonical kPa, not the typed PSI figure.
    //    Without this, a build that dropped the conversion and only relabelled
    //    the field would satisfy step 3.
    const tires = await request.get(`${API_BASE}/vehicles/${TEST_VEHICLE.vin}/tires`, {
      headers: admin.headers,
    })
    expect(tires.ok(), `Read back tires failed: ${tires.status()}`).toBeTruthy()
    const body = await tires.json()
    const front: { pressure_kpa: string | number } = body.tires.find(
      (tire: { position: string }) => tire.position === 'FL',
    )
    const storedKpa = Number(front.pressure_kpa)
    expect(storedKpa, '35 PSI must be stored as its kPa equivalent').toBeGreaterThan(241)
    expect(storedKpa).toBeLessThan(242)
  })
})

/**
 * The anonymous path, which is the only population `utils/unitPrefsStore.ts`
 * serves and the only one whose choice never touches the API.
 *
 * ★ IT HAS TO ARRANGE `auth_mode=none` ITSELF. `seedAndAuthenticate` sets the
 * instance to `local` (a fresh database defaults to `none`), so an "anonymous"
 * test that merely dropped the cookie would be redirected to `/login` and prove
 * nothing. The mode is flipped for this block and restored afterwards; the
 * suite runs with `workers: 1` and `fullyParallel: false`, so nothing else is
 * mid-flight while it is flipped.
 */
test.describe('Settings: units (auth_mode=none)', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  /**
   * Write the instance auth mode.
   *
   * @param value The mode to set.
   */
  async function setAuthMode(value: 'local' | 'none'): Promise<void> {
    // Sent on both flips. Going to `none` needs them; coming back the route
    // takes no user at all (`get_current_admin_user` returns None under
    // `auth_mode=none`), and passing a token it will not read is cheaper than a
    // branch that gets the direction wrong.
    const session = await adminSession()
    const context = await apiRequest.newContext({ baseURL: ROOT_BASE_URL })
    try {
      const response = await context.put(`${API_BASE}/settings/auth_mode`, {
        data: { value },
        headers: session.headers,
      })
      expect(
        response.ok(),
        `Set auth_mode=${value} failed: ${response.status()} ${await response.text()}`,
      ).toBeTruthy()
    } finally {
      await context.dispose()
    }
  }

  test.beforeAll(async () => {
    await setAuthMode('none')
  })

  test.afterAll(async () => {
    await setAuthMode('local')
  })

  test('a client with no account keeps its per-quantity choice', async ({ page }) => {
    await page.goto('/settings')
    const units = unitsCard(page)
    await expect(units).toBeVisible({ timeout: 15000 })

    // `bar` is the deliberate choice here: no preset and no instance default
    // resolves pressure to it, so every fallback rung answers something else.
    // Landing on `bar` after a reload can only mean the browser's own stored
    // set was read back.
    await units.getByRole('button', { name: 'Custom', exact: true }).click()
    await expect(page.locator('#unit-pressure')).toBeVisible({ timeout: 10000 })
    await page.selectOption('#unit-pressure', 'bar')
    await expect(page.getByText('Unit preference saved!').first()).toBeVisible({ timeout: 10000 })

    // The key the store OWNS, not one of the three legacy keys it migrates off.
    // Writing `unit_preference` instead is the second live regression this file
    // exists to catch: the store ignores it once its own key exists, so the
    // control appeared to work and changed nothing.
    const stored = await page.evaluate(() => localStorage.getItem('unit_prefs'))
    expect(stored ?? '', 'the anonymous choice must land in the key the store reads').toContain(
      '"pressure":"bar"',
    )

    await page.reload()
    await expect(units.getByRole('button', { name: 'Custom', exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
      { timeout: 15000 },
    )
    await expect(page.locator('#unit-pressure')).toHaveValue('bar')
    await expect(resolvedSentence(page)).toContainText(', bar,')
  })
})
