import { request as apiRequest, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import { test, expect } from './helpers/fixtures'
import { adminSessionFromStorageState, randomVin, seedLedger, type SeedLedger } from './helpers/seed'
import { TEST_VEHICLE } from './helpers/selectors'

/**
 * A date field gets the whole row on a phone (F5, D5).
 *
 * The Fuel form put Date beside Odometer at every width. On an iPhone the date
 * truncated ("Nov 2") and iOS's calendar popover, anchored to the narrow field,
 * ran off the right edge. Date rows now stack below `sm` like the Service form.
 *
 * Measured, not class-matched: the date input must span its grid row, and no
 * other field in that row may sit level with it. jsdom has no layout, so this
 * only works in a real browser. Whether stacking fixes the iOS popover itself
 * is the iPhone check (T8); no desktop engine draws that popover.
 */

const PHONE = { width: 390, height: 844 }
const TABLET = { width: 768, height: 1024 }

interface Row {
  dateWidth: number
  rowWidth: number
  /** Ids of the other fields in the date's grid row, and whether each sits level with the date. */
  others: { id: string; beside: boolean }[]
}

/** The date input's grid row, and what shares it. */
async function rowOf(date: Locator): Promise<Row> {
  return date.evaluate((input) => {
    const grid = input.closest('.grid')
    if (!grid) throw new Error(`#${input.id} is not in a grid row`)
    const box = input.getBoundingClientRect()
    const gridBox = grid.getBoundingClientRect()
    const others = [...grid.querySelectorAll<HTMLElement>('input, select, textarea')]
      .filter((el) => el !== input && el.getAttribute('type') !== 'hidden')
      .map((el) => {
        const r = el.getBoundingClientRect()
        return { id: el.id, beside: r.top < box.bottom && r.bottom > box.top }
      })
    return { dateWidth: box.width, rowWidth: gridBox.width, others }
  })
}

/** `sharesRowWith` names the row's other field; omit it for a date alone in its row. */
async function expectStacked(date: Locator, sharesRowWith?: string): Promise<void> {
  const row = await rowOf(date)
  // The row still holds the other field, or there is nothing to stack against.
  if (sharesRowWith) expect(row.others.map((o) => o.id)).toContain(sharesRowWith)
  expect(row.others.filter((o) => o.beside)).toEqual([])
  expect(row.dateWidth).toBeCloseTo(row.rowWidth, 0)
}

async function settledDrawer(page: Page, name: string): Promise<Locator> {
  const drawer = page.getByRole('dialog', { name })
  await expect(drawer).toBeVisible({ timeout: 15000 })
  await expect(drawer).toHaveClass(/translate-x-0/)
  await expect.poll(() => drawer.evaluate((el) => el.getAnimations().length)).toBe(0)
  return drawer
}

async function openFuel(page: Page): Promise<Locator> {
  await page.goto(`/quick-entry?action=fuel&vin=${TEST_VEHICLE.vin}`)
  return settledDrawer(page, 'Add Fuel Record')
}

test.describe('date fields stack on a phone (F5)', () => {
  test('Fuel: Date takes the whole row at 390px, Odometer goes under it', async ({ page }) => {
    await page.setViewportSize(PHONE)
    const drawer = await openFuel(page)
    await expectStacked(drawer.locator('#date'), 'odometer_km')
  })

  test('Fuel: Date and Odometer stay side by side at 768px (regression control)', async ({ page }) => {
    await page.setViewportSize(TABLET)
    const drawer = await openFuel(page)
    const row = await rowOf(drawer.locator('#date'))
    expect(row.others).toContainEqual({ id: 'odometer_km', beside: true })
    expect(row.dateWidth).toBeLessThan(row.rowWidth / 2)
  })

  test('Tax: both date rows stack at 390px', async ({ page }) => {
    await page.setViewportSize(PHONE)
    await page.goto(`/vehicles/${TEST_VEHICLE.vin}?tab=tax`)
    await page.getByRole('button', { name: /^Add (Your First )?Record$/ }).first().click()
    const drawer = await settledDrawer(page, 'Add Tax/Registration Record')
    await expectStacked(drawer.locator('#date'), 'tax_type')
    await expectStacked(drawer.locator('#renewal_date'), 'amount')
  })
})

// The other drawer forms with a two-column date row, opened from their vehicle
// tab. DEF, Propane and Spot rental need a diesel RV, seeded here; the rest use
// the shared test car.
const ROOT_BASE_URL = 'http://localhost:3000'
const AUTH_FILE = './e2e/.auth/user.json'

interface DateRowCase {
  form: string
  tab: string
  /** On the seeded diesel RV rather than the shared test car. */
  rv?: boolean
  button: RegExp
  title: string
  /** Each date input, and the field its row shares (none when the date is alone). */
  dates: { id: string; with?: string }[]
}

const CASES: DateRowCase[] = [
  { form: 'DEF', tab: 'def', rv: true, button: /^Add (DEF|Your First DEF Record)$/, title: 'Add DEF Record', dates: [{ id: 'date', with: 'odometer_km' }] },
  { form: 'Propane', tab: 'propane', rv: true, button: /^Add (Propane|Your First Record)$/, title: 'Add Propane Record', dates: [{ id: 'date' }] },
  {
    form: 'Spot rental',
    tab: 'spotrentals',
    rv: true,
    button: /^Add (Your First )?Rental$/,
    title: 'Add Spot Rental',
    dates: [{ id: 'check_in_date', with: 'check_out_date' }, { id: 'check_out_date', with: 'check_in_date' }],
  },
  {
    form: 'Warranty',
    tab: 'warranties',
    button: /^Add (Your First )?Warranty$/,
    title: 'Add Warranty',
    dates: [{ id: 'start_date', with: 'end_date' }, { id: 'end_date', with: 'start_date' }],
  },
  {
    form: 'Insurance policy',
    tab: 'insurance',
    button: /^Add (Your First )?Insurance Policy$/,
    title: 'Add Insurance Policy',
    dates: [{ id: 'start_date', with: 'end_date' }, { id: 'end_date', with: 'start_date' }],
  },
  { form: 'Recall', tab: 'recalls', button: /^Add (Recall|Manual Entry)$/, title: 'Add Recall', dates: [{ id: 'date_announced', with: 'nhtsa_campaign_number' }] },
  { form: 'Financing', tab: 'financing', button: /^Add (Your First )?Record$/, title: 'Add Financing Record', dates: [{ id: 'date', with: 'category' }] },
  { form: 'Toll transaction', tab: 'tolls', button: /^Add (Your First )?Transaction$/, title: 'Add Toll Transaction', dates: [{ id: 'transaction_date', with: 'amount' }] },
]

test.describe('date fields stack on a phone: the other drawer forms (F5)', () => {
  let api: APIRequestContext
  let ledger: SeedLedger
  let rvVin = ''

  test.beforeAll(async () => {
    api = await apiRequest.newContext({ baseURL: ROOT_BASE_URL })
    const admin = await adminSessionFromStorageState(api, `${ROOT_BASE_URL}/api`, AUTH_FILE)
    ledger = seedLedger(api, `${ROOT_BASE_URL}/api`, admin.headers)
    // VehicleSeed doesn't list fuel_type, so it rides in a spread like hours.spec does.
    const extra: Record<string, unknown> = { fuel_type: 'Diesel' }
    rvVin = await ledger.vehicle({
      vin: randomVin('DATE'),
      nickname: 'E2E Date Rig',
      vehicle_type: 'RV',
      year: 2015,
      make: 'DateRigMake',
      model: 'DateRigModel',
      ...extra,
    })
  })

  test.afterAll(async () => {
    try {
      await ledger?.cleanup()
    } finally {
      await api?.dispose()
    }
  })

  for (const c of CASES) {
    test(`${c.form}: every date row stacks at 390px`, async ({ page }) => {
      await page.setViewportSize(PHONE)
      await page.goto(`/vehicles/${c.rv ? rvVin : TEST_VEHICLE.vin}?tab=${c.tab}`)
      await page.getByRole('button', { name: c.button }).first().click()
      const drawer = await settledDrawer(page, c.title)
      for (const date of c.dates) await expectStacked(drawer.locator(`#${date.id}`), date.with)
    })
  }
})
