import { request as apiRequest, type APIRequestContext, type Locator, type Page } from '@playwright/test'

import { test, expect } from './helpers/fixtures'
import { openFuelRecordForm } from './helpers/forms'
import { adminSessionFromStorageState, randomVin, seedLedger, type SeedLedger } from './helpers/seed'

/**
 * The modal stack in a real browser: a nested drawer over a record drawer.
 * Esc closes only the top one, the parent is inert under it, and once it's
 * gone Tab stays inside the parent. Same deal for a confirm over a drawer.
 */

const ROOT_BASE_URL = 'http://localhost:3000'
const API_BASE = `${ROOT_BASE_URL}/api`
const AUTH_FILE = './e2e/.auth/user.json'

const CAR = {
  nickname: 'E2E Stack Car',
  vehicle_type: 'Car',
  year: 2018,
  make: 'StackMake',
  model: 'StackModel',
}
// Matches nothing in the address book, so the picker offers "+ Add".
const NEW_STATION = 'Xjq Stack Fuel'
const TIRE = 'E2E Stack Tire'

let api: APIRequestContext
let ledger: SeedLedger
let adminHeaders: Record<string, string> = {}
let vin = ''

test.beforeAll(async () => {
  api = await apiRequest.newContext({ baseURL: ROOT_BASE_URL })
  const admin = await adminSessionFromStorageState(api, API_BASE, AUTH_FILE)
  adminHeaders = admin.headers
  ledger = seedLedger(api, API_BASE, admin.headers)
  vin = await ledger.vehicle({ vin: randomVin('STAK'), ...CAR })

  // A mounted tire with one reading, so its history drawer has a Delete to confirm.
  // Neither confirm test goes through with it, so the reading outlives both.
  const tire = await api.post(`${API_BASE}/vehicles/${vin}/tires/create-and-mount`, {
    headers: admin.headers,
    data: { vin, position: 'FL', brand: TIRE, tread_depth_mm: 8, mounted_on: '2026-01-01', mounted_odometer_km: 10000 },
  })
  expect(tire.status(), await tire.text()).toBe(201)
  const tireId = (await tire.json()).id
  const reading = await api.post(`${API_BASE}/vehicles/${vin}/tires/${tireId}/readings`, {
    headers: admin.headers,
    data: { recorded_at: '2026-02-01', tread_depth_mm: 7, odometer_km: 12000 },
  })
  expect(reading.status(), await reading.text()).toBe(201)
})

test.afterAll(async () => {
  try {
    await ledger?.cleanup()
  } finally {
    await api?.dispose()
  }
})

/** Whether focus sits inside this element right now. */
async function holdsFocus(el: Locator): Promise<boolean> {
  return el.evaluate((node) => node.contains(document.activeElement))
}

/** Whether a real click on the middle of this element would land on it. */
async function hitsItself(el: Locator): Promise<boolean> {
  return el.evaluate((node) => {
    const box = node.getBoundingClientRect()
    const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2)
    return hit !== null && node.contains(hit)
  })
}

/** From the Tires sub-tab, opens the seeded tire's history and asks to delete its reading. */
async function askToDeleteReading(page: Page): Promise<{ history: Locator; deleteReading: Locator; confirm: Locator }> {
  await page.getByRole('tab', { name: 'Maintenance' }).click()
  await page.getByRole('tab', { name: 'Tires' }).click()
  const card = page.locator('.rounded-card', { hasText: TIRE }).first()
  await expect(card).toBeVisible({ timeout: 10000 })
  // The card's own text opens the history (#179).
  await card.getByText(TIRE, { exact: true }).click()
  const history = page.getByRole('dialog', { name: /^History/ })
  await expect(history).toBeVisible({ timeout: 5000 })
  const deleteReading = history.getByRole('button', { name: /^Delete the reading of / })
  await deleteReading.click()
  const confirm = page.getByRole('alertdialog')
  await expect(confirm).toBeVisible()
  await expect(confirm).toHaveAccessibleName(/^Delete the reading of /)
  return { history, deleteReading, confirm }
}

test.describe('Modal stack', () => {
  test('Esc closes only the nested drawer, then Tab cycles inside the parent', async ({ page }) => {
    await openFuelRecordForm(page, vin)
    const parent = page.getByRole('dialog', { name: 'Add Fuel Record' })

    const moreDetails = parent.getByRole('button', { name: /more details/i })
    if ((await moreDetails.getAttribute('aria-expanded')) !== 'true') {
      await moreDetails.click()
    }
    const station = parent.locator('#station_name_freetext')
    await station.pressSequentially(NEW_STATION, { delay: 30 })
    await parent.getByRole('option', { name: `Add "${NEW_STATION}" to address book` }).click()

    const nested = page.getByRole('dialog', { name: 'Add station' })
    await expect(nested).toBeVisible()
    await expect(parent).toHaveAttribute('inert', '')
    await expect(nested).not.toHaveAttribute('inert')
    await expect.poll(() => holdsFocus(nested), { message: 'focus never moved into the nested drawer' }).toBe(true)

    await page.keyboard.press('Escape')
    await expect(nested).toBeHidden()
    await expect(parent).toBeVisible()
    await expect(parent).not.toHaveAttribute('inert')
    await expect.poll(() => holdsFocus(parent), { message: 'focus did not come back to the parent' }).toBe(true)

    // Shift+Tab off the header Close wraps to the parent's last control, and Tab wraps back.
    const close = parent.getByRole('button', { name: 'Close' })
    await close.focus()
    await page.keyboard.press('Shift+Tab')
    expect(await holdsFocus(parent), 'Shift+Tab left the parent drawer').toBe(true)
    await expect(close).not.toBeFocused()
    await page.keyboard.press('Tab')
    await expect(close).toBeFocused()
  })

  test('a confirm over the tire history drawer is live, traps Tab, and Esc closes only it', async ({ page }) => {
    await page.goto(`/vehicles/${vin}`)
    await expect(page.getByRole('heading', { name: CAR.nickname })).toBeVisible({ timeout: 15000 })
    const { history, deleteReading, confirm } = await askToDeleteReading(page)

    // The inert trap: portalled out of #root, under no inert ancestor, and a real click lands on it.
    const yes = confirm.getByRole('button', { name: 'Delete' })
    const live = await yes.evaluate((el) => ({
      outsideRoot: !document.getElementById('root')!.contains(el),
      notInert: el.closest('[inert]') === null,
    }))
    expect(live).toEqual({ outsideRoot: true, notInert: true })
    expect(await hitsItself(yes), 'a click on the confirm button lands on something else').toBe(true)
    await expect(history).toHaveAttribute('inert', '')

    await expect(confirm.getByRole('button', { name: 'Cancel' })).toBeFocused()
    await page.keyboard.press('Tab')
    expect(await holdsFocus(confirm), 'first Tab left the confirm').toBe(true)
    await page.keyboard.press('Tab')
    expect(await holdsFocus(confirm), 'second Tab left the confirm').toBe(true)

    await page.keyboard.press('Escape')
    await expect(confirm).toBeHidden()
    await expect(history).toBeVisible()
    await expect(history).not.toHaveAttribute('inert')
    expect(await hitsItself(deleteReading), 'the drawer delete is still covered').toBe(true)
  })

  test('Back with a confirm open leaves the page, closes it, and deletes nothing', async ({ page }) => {
    const deletes: string[] = []
    page.on('request', (request) => {
      if (request.method() === 'DELETE') deletes.push(request.url())
    })
    // In-app entry, so Back stays in the app. A page.goto here would make Back
    // leave for about:blank and pass on any build.
    await page.goto('/')
    await expect(page.getByRole('heading', { name: /garage/i })).toBeVisible({ timeout: 15000 })
    // The card prints the VIN, not the nickname.
    await page.locator('article', { hasText: vin }).getByRole('button', { name: /view details/i }).click()
    await expect(page.getByRole('heading', { name: CAR.nickname })).toBeVisible({ timeout: 15000 })
    const { confirm } = await askToDeleteReading(page)

    await page.goBack()
    await expect(page.getByRole('heading', { name: /garage/i })).toBeVisible({ timeout: 15000 })
    await expect(confirm).toBeHidden()
    expect(deletes).toEqual([])
  })

  // Linux Chromium has no BarcodeDetector, so Scan opens the typed-code dialog.
  // React events bubble through its portal, so a leaked submit would save the
  // supply and close the drawer.
  test('a typed barcode over the supply drawer fills the field and saves nothing', async ({ page }) => {
    const name = `E2E Barcode ${Date.now()}`
    const made = await api.post(`${API_BASE}/supplies`, {
      headers: adminHeaders,
      data: { name, unit_type: 'count' },
    })
    expect(made.status(), await made.text()).toBe(201)
    const supplyId = (await made.json()).id as number
    try {
      const writes: string[] = []
      page.on('request', (request) => {
        if (request.url().includes('/api/supplies') && request.method() !== 'GET') {
          writes.push(`${request.method()} ${request.url()}`)
        }
      })
      await page.goto('/supplies')
      await page.getByPlaceholder('Search supplies...').fill(name)
      await page.getByRole('button', { name: 'Edit', exact: true }).click()
      const drawer = page.getByRole('dialog', { name: 'Edit Supply' })
      await expect(drawer).toBeVisible({ timeout: 10000 })

      await drawer.getByRole('button', { name: 'Scan', exact: true }).click()
      const manual = page.getByRole('dialog', { name: /Enter the barcode manually/ })
      await expect(manual).toBeVisible()
      await manual.getByRole('textbox').fill('0123456789012')
      await page.keyboard.press('Enter')

      await expect(manual).toBeHidden()
      await expect(drawer.locator('#barcode')).toHaveValue('0123456789012')
      // A leaked submit fires its PUT straight away; give it a beat to show up.
      await page.waitForTimeout(500)
      await expect(drawer).toBeVisible()
      expect(writes).toEqual([])
    } finally {
      const gone = await api.delete(`${API_BASE}/supplies/${supplyId}`, { headers: adminHeaders })
      expect(gone.ok(), `delete supply ${supplyId}: ${gone.status()}`).toBeTruthy()
    }
  })
})
