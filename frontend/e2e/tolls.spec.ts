import { request as apiRequest, type APIRequestContext } from '@playwright/test'

import { test, expect } from './helpers/fixtures'
import { captureApiRequest } from './helpers/forms'
import { adminSessionFromStorageState, randomVin, seedLedger, type SeedLedger } from './helpers/seed'

/**
 * The toll tag form's country-then-system picker in a real browser. The unit
 * tests drive the form in jsdom; this one adds Chromium's own select, the
 * browser's country names and the backend saving the system.
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

test.describe('Toll tags', () => {
  test('country filters the systems, a new country clears one it lacks, and a typed listed name saves as the listed one', async ({
    page,
  }) => {
    const vin = await ledger.vehicle({
      vin: randomVin('TOLL'),
      nickname: 'E2E Toll Rig',
      vehicle_type: 'Car',
      year: 1999,
      make: 'TollRigMake',
      model: 'TollRigModel',
    })

    await page.goto(`/vehicles/${vin}?tab=tolls`)
    await page.getByRole('button', { name: 'Add Your First Toll Tag' }).click()
    const form = page.getByRole('dialog', { name: 'Add Toll Tag' })
    const country = form.locator('#toll_country')
    const system = form.locator('#toll_system')

    // By value: the country labels come from the browser's ICU data.
    await country.selectOption('IT')
    await expect(system.locator('option[value="Telepass"]')).toHaveCount(1)
    await expect(system.locator('option[value="SunPass"]')).toHaveCount(0)
    await system.selectOption('Telepass')

    await country.selectOption('US')
    await expect(system).toHaveValue('')

    // Chromium blanks the select by itself, so only a trip back to IT shows whether the form
    // forgot Telepass too. If it didn't, the empty-looking select would save Telepass.
    await country.selectOption('IT')
    await expect(system).toHaveValue('')
    await form.getByRole('button', { name: 'Add Tag' }).click()
    await expect(form.getByText('Toll system is required')).toBeVisible()

    await country.selectOption('US')
    await system.selectOption('__other__')
    const name = form.locator('#toll_system_other')
    await expect(name).toBeVisible()
    await expect(name).toBeFocused()
    await name.fill('sunpass ')
    await expect(form.getByText('Saves as SunPass, which is on the list.')).toBeVisible()

    await form.locator('#tag_number').fill('0012345678')
    const posted = captureApiRequest(page, 'POST', new RegExp(`/api/vehicles/${vin}/toll-tags$`))
    await form.getByRole('button', { name: 'Add Tag' }).click()
    const body = await posted
    expect(body.toll_system).toBe('SunPass')
    // Country only filters the list, so it never goes to the API.
    expect(body).not.toHaveProperty('toll_country')
    await expect(form).toBeHidden({ timeout: 10000 })

    const saved = page.getByRole('heading', { name: 'SunPass', exact: true })
    await expect(saved).toBeVisible({ timeout: 10000 })
    // The vehicle header has its own Edit, so go through the tag's card.
    const card = saved.locator('xpath=ancestor::div[contains(@class, "rounded-card")][1]')
    await card.getByRole('button', { name: 'Edit', exact: true }).click()
    const edit = page.getByRole('dialog', { name: 'Edit Toll Tag' })
    await expect(edit.locator('#toll_country')).toHaveValue('US')
    await expect(edit.locator('#toll_system')).toHaveValue('SunPass')
  })
})
