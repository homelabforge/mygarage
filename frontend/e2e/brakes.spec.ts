import { request as apiRequest, type APIRequestContext } from '@playwright/test'

import { test, expect } from './helpers/fixtures'
import { adminSessionFromStorageState, randomVin, seedLedger, type SeedLedger } from './helpers/seed'

/**
 * Brake tracking (#202), driven through the browser: the tab is reachable by
 * clicking, the drawers submit shapes the API accepts, and what comes back
 * renders on the right corner. The component tests mock the hooks, so none of
 * that is visible to them.
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

/** A vehicle of this file's own, fresh every run, deleted in afterAll. */
async function brakeVehicle(): Promise<string> {
  return ledger.vehicle({
    vin: randomVin('BRAK'),
    nickname: 'E2E Brake Rig',
    vehicle_type: 'Car',
    year: 1999,
    make: 'BrakeRigMake',
    model: 'BrakeRigModel',
  })
}

async function openBrakes(page: import('@playwright/test').Page, vin: string) {
  await page.goto(`/vehicles/${vin}`)
  await expect(page.getByRole('heading', { name: 'E2E Brake Rig' })).toBeVisible({ timeout: 15000 })
  await page.getByRole('tab', { name: 'Maintenance' }).click()
  await page.getByRole('tab', { name: 'Brakes' }).click()
  await expect(page.getByRole('heading', { name: 'Brakes', exact: true })).toBeVisible({ timeout: 10000 })
}

test.afterAll(async () => {
  try {
    await ledger.cleanup()
  } finally {
    await api.dispose()
  }
})

test.describe('Brakes', () => {
  test('set the rear axle to drum, log all four corners, then a pad job starts the front over', async ({
    page,
  }) => {
    const vin = await brakeVehicle()
    await openBrakes(page, vin)

    // Four corners, nothing measured yet.
    await expect(page.getByText('Not measured', { exact: true })).toHaveCount(4)

    await page.getByRole('button', { name: 'Axle setup' }).click()
    const setup = page.getByRole('dialog')
    await setup.getByRole('button', { name: 'Drum' }).nth(1).click()
    await setup.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('Axle setup saved')).toBeVisible()
    await expect(page.getByText('Drum · lining 5.0 mm new, 1.5 mm minimum')).toHaveCount(2)

    await page.getByRole('button', { name: 'Log measurements' }).click()
    const log = page.getByRole('dialog')
    await log.locator('#brake-log-FL-inner_pad_mm').fill('4.2')
    await log.locator('#brake-log-FL-outer_pad_mm').fill('6')
    await log.locator('#brake-log-FR-inner_pad_mm').fill('8')
    await log.locator('#brake-log-RL-shoe_mm').fill('3.5')
    await log.locator('#brake-log-RR-shoe_mm').fill('1.2')
    await log.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('Brake measurements saved')).toBeVisible()

    // FL is in the due-soon band, RR is under its 1.5 mm minimum.
    await expect(page.getByText('Due soon', { exact: true })).toBeVisible()
    await expect(page.getByText('Replace now', { exact: true }).first()).toBeVisible()

    // A brake job from FL's card covers the front axle and fits new pads.
    const flCard = page.locator('.rounded-card', { hasText: 'Front Left' }).first()
    await flCard.getByRole('button', { name: 'Brake job' }).click()
    const job = page.getByRole('dialog')
    await expect(job.locator('#brake-job-new-front')).toHaveValue('10')
    await job.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('Brake job saved')).toBeVisible()

    await expect(page.getByText('Due soon', { exact: true })).toHaveCount(0)
    await expect(flCard.getByText('10.0 mm').first()).toBeVisible()
  })
})
