import { request as apiRequest, type APIRequestContext, type Locator, type Page } from '@playwright/test'

import { test, expect } from './helpers/fixtures'
import { openFuelRecordForm } from './helpers/forms'
import { adminSessionFromStorageState, randomVin, seedLedger, type SeedLedger } from './helpers/seed'

/**
 * The fill-up station picker and its twin on spot rentals (#194).
 *
 * Two bugs, both only visible with a real server and real timers. A station
 * saved on the Address Book page has the category "Gas Station" and no POI
 * type, and the fill-up asked for the POI type only, so it never offered one.
 * And a pick wrote the name into the box, the box's value drove the search, and
 * the search reopened the list a debounce later.
 */

const ROOT_BASE_URL = 'http://localhost:3000'
const API_BASE = `${ROOT_BASE_URL}/api`
const AUTH_FILE = './e2e/.auth/user.json'

/** An RV: it has a Fuel tab AND a Spot Rentals tab, so one vehicle serves both pickers. */
const RIG = {
  nickname: 'E2E Picker RV',
  vehicle_type: 'RV',
  year: 2003,
  make: 'PickerRigMake',
  model: 'PickerRigModel',
}
// The first three letters are what gets typed, so they match nothing else.
const STATION = { business_name: 'Qzv Fuel Stop', city: 'Testville', state: 'TX', category: 'Gas Station' }
const PARK = { business_name: 'Wkj RV Haven', city: 'Testville', state: 'TX', category: 'RV Park' }

let api: APIRequestContext
let ledger: SeedLedger
let rigVin = ''
let stationId = 0

test.beforeAll(async () => {
  api = await apiRequest.newContext({ baseURL: ROOT_BASE_URL })
  const admin = await adminSessionFromStorageState(api, API_BASE, AUTH_FILE)
  ledger = seedLedger(api, API_BASE, admin.headers)
  rigVin = await ledger.vehicle({ vin: randomVin('PICK'), ...RIG })
  // The Address Book page's shape: a category, no poi_category.
  stationId = await ledger.addressBookEntry(STATION)
  await ledger.addressBookEntry(PARK)
})

test.afterAll(async () => {
  try {
    await ledger.cleanup()
  } finally {
    await api.dispose()
  }
})

/** The fields of a listed fill-up this spec reads back. */
interface FuelRow {
  station_address_book_id: number | null
  station_name: string | null
}

/** The autocomplete's own wrapper: the input, its spinner and its list. */
function pickerAround(input: Locator): Locator {
  return input.locator('xpath=..')
}

/**
 * Type three letters, see the entry offered, pick it, and check the list stays
 * shut for well past the search debounce.
 *
 * Read every 100 ms rather than once at the end: the bug reopened the list
 * about 300 ms after the pick, so the moment you look decides what you see.
 */
async function pickAndWatch(page: Page, input: Locator, name: string): Promise<void> {
  const picker = pickerAround(input)
  // The one panel under the box: results, "Searching", or "no matches" with its + Add option.
  const list = picker.locator(':scope > div.z-50')

  await input.pressSequentially(name.slice(0, 3), { delay: 50 })
  const option = picker.getByRole('option', { name })
  await expect(option, `${name} was not offered`).toBeVisible({ timeout: 5000 })
  // The list locator has to see the open list, or "shut" below proves nothing.
  await expect(list).toHaveCount(1)

  await option.click()
  await expect(input).toHaveValue(name)
  for (let waited = 0; waited <= 1500; waited += 100) {
    expect(await list.count(), `the list was open ${waited} ms after the pick`).toBe(0)
    await page.waitForTimeout(100)
  }
}

test.describe('Station picker (#194)', () => {
  test('a Gas Station entry is offered on a fill-up, stays picked, and saves as the station', async ({
    page,
  }) => {
    await openFuelRecordForm(page, rigVin)
    const today = new Date().toISOString().split('T')[0]
    await page.locator('#date').fill(today)
    await page.locator('#odometer_km').fill('48280')
    await page.locator('#liters').fill('47.318')
    await page.locator('#cost').fill('43.75')

    const moreDetails = page.getByRole('button', { name: /more details/i })
    if ((await moreDetails.getAttribute('aria-expanded')) !== 'true') {
      await moreDetails.click()
    }

    await pickAndWatch(page, page.locator('#station_name_freetext'), STATION.business_name)

    await page.getByRole('button', { name: /create/i }).click()
    await expect(page.getByText('Add Fuel Record')).not.toBeVisible({ timeout: 10000 })

    // The contract, from the API: the fill-up points at that entry, not at a
    // freetext name or a fresh duplicate. Polled, so the read can't beat the
    // create whatever the wait above saw.
    const listFuel = async (): Promise<FuelRow[]> =>
      (await ledger.get(`/vehicles/${rigVin}/fuel`)).records as FuelRow[]
    await expect
      .poll(async () => (await listFuel()).length, {
        message: 'the fill-up never reached the API',
        timeout: 10000,
      })
      .toBe(1)
    const records = await listFuel()
    expect(records).toHaveLength(1)
    expect(records[0].station_address_book_id).toBe(stationId)
    expect(records[0].station_name).toBe(STATION.business_name)
  })

  test('an RV Park entry picked as a spot rental location stays picked', async ({ page }) => {
    await page.goto(`/vehicles/${rigVin}?tab=spotrentals`)
    await expect(page.getByRole('heading', { name: 'Spot Rentals', exact: true })).toBeVisible({
      timeout: 15000,
    })
    await page.getByRole('button', { name: 'Add Rental', exact: true }).click()
    const input = page.locator('#location_name')
    await expect(input).toBeVisible({ timeout: 5000 })

    await pickAndWatch(page, input, PARK.business_name)

    await page.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(input).toBeHidden({ timeout: 10000 })
  })
})
