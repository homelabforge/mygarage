import { request as apiRequest, type APIRequestContext, type Locator } from '@playwright/test'

import { test, expect } from './helpers/fixtures'
import { openFuelRecordForm } from './helpers/forms'
import { adminSessionFromStorageState, randomVin, seedLedger, type SeedLedger } from './helpers/seed'

/**
 * The modal stack in a real browser: a nested drawer over a record drawer.
 * Esc closes only the top one, the parent is inert under it, and once it's
 * gone Tab stays inside the parent.
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

let api: APIRequestContext
let ledger: SeedLedger
let vin = ''

test.beforeAll(async () => {
  api = await apiRequest.newContext({ baseURL: ROOT_BASE_URL })
  const admin = await adminSessionFromStorageState(api, API_BASE, AUTH_FILE)
  ledger = seedLedger(api, API_BASE, admin.headers)
  vin = await ledger.vehicle({ vin: randomVin('STAK'), ...CAR })
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
})
