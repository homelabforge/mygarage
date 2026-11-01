import { request as apiRequest, type APIRequestContext, type Page } from '@playwright/test'

import { test, expect } from './helpers/fixtures'
import { openFuelRecordForm } from './helpers/forms'
import { adminSessionFromStorageState, randomVin, seedLedger, type SeedLedger } from './helpers/seed'

/**
 * Engine hours, driven through the browser: the tab only an hours vehicle gets,
 * a manual reading, and a fill-up that asks for hours instead of miles and
 * comes back with a per-hour rate and a synced hours row. The component tests
 * mock every hook, so none of the layers meeting is visible to them.
 */

const ROOT_BASE_URL = 'http://localhost:3000'
const API_BASE = `${ROOT_BASE_URL}/api`
const AUTH_FILE = './e2e/.auth/user.json'

let api: APIRequestContext
let ledger: SeedLedger

test.beforeAll(async () => {
  api = await apiRequest.newContext({ baseURL: ROOT_BASE_URL })
  const admin = await adminSessionFromStorageState(api, API_BASE, AUTH_FILE)
  ledger = seedLedger(api, API_BASE, admin.headers)
})

test.afterAll(async () => {
  try {
    await ledger?.cleanup()
  } finally {
    await api?.dispose()
  }
})

/** An hours-only vehicle of this file's own, fresh every run. */
async function hoursVehicle(): Promise<string> {
  // VehicleSeed doesn't list usage_unit or fuel_type, so they ride in a spread like tires.spec does.
  const extra: Record<string, unknown> = { usage_unit: 'hours', fuel_type: 'Gasoline' }
  return ledger.vehicle({
    vin: randomVin('HRS'),
    nickname: 'E2E Hours Rig',
    vehicle_type: 'Car',
    year: 1999,
    make: 'HoursRigMake',
    model: 'HoursRigModel',
    ...extra,
  })
}

/** There's no `?tab=hours` deep link, so click through like a user would. */
async function openEngineHours(page: Page, vin: string): Promise<void> {
  await page.goto(`/vehicles/${vin}`)
  await expect(page.getByRole('heading', { name: 'E2E Hours Rig' })).toBeVisible({ timeout: 15000 })
  await page.getByRole('tab', { name: 'Maintenance' }).click()
  await page.getByRole('tab', { name: 'Engine Hours' }).click()
  await expect(page.getByRole('heading', { name: 'Engine Hours Readings' })).toBeVisible({ timeout: 10000 })
}

test.describe('Engine hours', () => {
  test('a manual reading lists, a fill-up takes hours not miles, and it shows a per-hour rate and a Fuel row', async ({
    page,
  }) => {
    const vin = await hoursVehicle()

    await openEngineHours(page, vin)
    await page.getByRole('button', { name: 'Add First Reading' }).click()
    const form = page.getByRole('dialog', { name: 'Add Engine Hours Reading' })
    await form.locator('#date').fill('2026-04-01')
    await form.locator('#engine_hours').fill('50')
    await form.getByRole('button', { name: 'Create' }).click()
    await expect(form).toBeHidden({ timeout: 10000 })
    const hoursTable = page.getByRole('table', { name: 'Engine hours reading history' })
    const manualRow = hoursTable.getByRole('row').filter({ hasText: '50.0 hr' })
    await expect(manualRow).toHaveCount(1)
    await expect(manualRow).toContainText('Manual')

    // The first full fill goes in through the API, so the UI one has something to measure from.
    await ledger.post(`/vehicles/${vin}/fuel`, {
      vin,
      date: '2026-05-01',
      engine_hours: 100,
      liters: '40',
      is_full_tank: true,
    })

    await openFuelRecordForm(page, vin)
    const fuel = page.getByRole('dialog', { name: 'Add Fuel Record' })
    await expect(fuel.locator('#engine_hours')).toBeVisible()
    await expect(fuel.locator('#odometer_km')).toHaveCount(0)
    await fuel.locator('#date').fill('2026-06-01')
    await fuel.locator('#engine_hours').fill('110')
    // Litres or gallons depending on what earlier specs left the units on. Only the suffix is asserted.
    await fuel.locator('#liters').fill('30')
    await expect(fuel.locator('#is_full_tank')).toBeChecked()
    await fuel.getByRole('button', { name: 'Create' }).click()
    await expect(fuel).toBeHidden({ timeout: 10000 })

    // Only the second fill has an interval to measure, so exactly one rate badge.
    const fuelTable = page.getByRole('table', { name: 'Fuel fill-up history' })
    await expect(fuelTable.getByRole('row')).toHaveCount(3)
    await expect(fuelTable.getByText(/\/hr\b/)).toHaveCount(1)

    await openEngineHours(page, vin)
    const fuelRow = hoursTable.getByRole('row').filter({ hasText: '110.0 hr' })
    await expect(fuelRow).toHaveCount(1)
    await expect(fuelRow).toContainText('Fuel')
  })
})
