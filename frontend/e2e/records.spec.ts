import { test, expect } from './helpers/fixtures'
import { TEST_VEHICLE } from './helpers/selectors'

/**
 * Navigate to the Fuel tab for the test vehicle.
 * Shared setup for all fuel record tests.
 */
async function goToFuelTab(page: import('@playwright/test').Page): Promise<void> {
  await page.goto(`/vehicles/${TEST_VEHICLE.vin}?tab=fuel`)
  await expect(
    page.getByRole('heading', { name: TEST_VEHICLE.nickname })
  ).toBeVisible({ timeout: 15000 })
  await expect(page.getByText('Fuel History')).toBeVisible({ timeout: 10000 })
}

test.describe('Fuel Record Workflow', () => {
  test('add fuel record and verify it appears in the list', async ({ page }) => {
    await goToFuelTab(page)

    // Click "Add Fill-up" button
    await page.getByRole('button', { name: /add fill-up/i }).click()

    // Fuel record form modal should appear
    await expect(page.getByText('Add Fuel Record')).toBeVisible({ timeout: 5000 })

    // Fill in the form fields. ``odometer_km`` is required by the
    // backend cross-field validator added in v2.27.0-rc2 (#69) — rc1
    // accepted records with no odometer; rc2 doesn't.
    const today = new Date().toISOString().split('T')[0]
    await page.locator('#date').fill(today)
    await page.locator('#odometer_km').fill('48280')
    await page.locator('#liters').fill('47.318')
    await page.locator('#cost').fill('43.75')

    // Submit the form
    await page.getByRole('button', { name: /create/i }).click()

    // Wait for the form modal to close
    await expect(page.getByText('Add Fuel Record')).not.toBeVisible({ timeout: 10000 })

    // Reload the page to bypass react-query cache staleness
    await page.goto(`/vehicles/${TEST_VEHICLE.vin}?tab=fuel`)
    await expect(page.getByText('Fuel History')).toBeVisible({ timeout: 10000 })

    // Verify the list now shows at least one record (the record count header changes)
    await expect(page.getByText(/\(1 record/)).toBeVisible({ timeout: 10000 })

    // Now delete the record to clean up
    page.on('dialog', (dialog) => dialog.accept())
    const deleteButton = page.locator('button[title="Delete"]').first()
    await deleteButton.click()

    // Verify the record is removed — back to empty state
    await expect(page.getByText('No fuel records yet')).toBeVisible({ timeout: 10000 })
  })

  test('add fuel record with details, then delete', async ({ page }) => {
    await goToFuelTab(page)

    await page.getByRole('button', { name: /add fill-up/i }).click()
    await expect(page.getByText('Add Fuel Record')).toBeVisible({ timeout: 5000 })

    const today = new Date().toISOString().split('T')[0]
    await page.locator('#date').fill(today)
    await page.locator('#odometer_km').fill('80467')
    await page.locator('#liters').fill('56.781')
    await page.locator('#price_per_unit').fill('0.925')

    await page.getByRole('button', { name: /create/i }).click()
    await expect(page.getByText('Add Fuel Record')).not.toBeVisible({ timeout: 10000 })

    // Reload to see the updated list
    await page.goto(`/vehicles/${TEST_VEHICLE.vin}?tab=fuel`)
    await expect(page.getByText('Fuel History')).toBeVisible({ timeout: 10000 })
    await expect(page.getByText(/\(\d+ record/)).toBeVisible({ timeout: 10000 })

    // Clean up: delete all records
    page.on('dialog', (dialog) => dialog.accept())
    const deleteButtons = page.locator('button[title="Delete"]')
    const count = await deleteButtons.count()
    for (let i = 0; i < count; i++) {
      await deleteButtons.first().click()
      await page.waitForTimeout(500)
    }
  })

  test('fill-up time is unambiguous (12h AM/PM) and round-trips on edit (#109)', async ({
    page,
  }) => {
    await goToFuelTab(page)

    await page.getByRole('button', { name: /add fill-up/i }).click()
    await expect(page.getByText('Add Fuel Record')).toBeVisible({ timeout: 5000 })

    // Required top-level fields (same pattern as the other fuel tests)
    const today = new Date().toISOString().split('T')[0]
    await page.locator('#date').fill(today)
    await page.locator('#odometer_km').fill('92340')
    await page.locator('#liters').fill('45.500')
    await page.locator('#cost').fill('50.00')

    // Expand "More details" to reach the 24-hour fill-up time fields (#109)
    const moreDetailsToggle = page.getByRole('button', { name: /more details/i })
    if ((await moreDetailsToggle.getAttribute('aria-expanded')) !== 'true') {
      await moreDetailsToggle.click()
    }
    // 12-hour mode is the default: enter the hour, then pick AM/PM explicitly —
    // a bare hour is never silently assigned a meridiem. The fill-up date comes
    // from the top-level #date field (set to `today` above).
    await page.locator('#filled_at_time').fill('10:00')
    await page.getByRole('button', { name: 'PM' }).click()

    // Capture the create request and assert the recomputed payload — proves the
    // 12h control (10:00 + PM) normalizes to canonical 22:00 and the form
    // recomputes filled_at from the record date + time at submit.
    const [req] = await Promise.all([
      page.waitForRequest(
        (r) => /\/vehicles\/[^/]+\/fuel$/.test(new URL(r.url()).pathname) && r.method() === 'POST'
      ),
      page.getByRole('button', { name: /create/i }).click(),
    ])
    expect(JSON.parse(req.postData() ?? '{}').filled_at).toBe(`${today}T22:00`)

    await expect(page.getByText('Add Fuel Record')).not.toBeVisible({ timeout: 10000 })

    // Reload to bypass react-query cache staleness, then reopen the saved
    // record's edit form (a fresh FuelRecordForm mount) and confirm the time
    // reads back unambiguously as 22:00 — not 02:20 or 10:00 pm.
    await page.goto(`/vehicles/${TEST_VEHICLE.vin}?tab=fuel`)
    await expect(page.getByText('Fuel History')).toBeVisible({ timeout: 10000 })

    await page.locator('button[title="Edit"]').first().click()
    await expect(page.getByText('Edit Fuel Record')).toBeVisible({ timeout: 5000 })

    const editMoreDetailsToggle = page.getByRole('button', { name: /more details/i })
    if ((await editMoreDetailsToggle.getAttribute('aria-expanded')) !== 'true') {
      await editMoreDetailsToggle.click()
    }
    await expect(page.locator('#filled_at_time')).toHaveValue('10:00')
    await expect(page.getByRole('button', { name: 'PM' })).toHaveAttribute('aria-pressed', 'true')

    // Close without saving, then clean up
    await page.getByRole('button', { name: /cancel/i }).click()
    await expect(page.getByText('Edit Fuel Record')).not.toBeVisible({ timeout: 5000 })

    page.on('dialog', (dialog) => dialog.accept())
    const deleteButton = page.locator('button[title="Delete"]').first()
    await deleteButton.click()
    await expect(page.getByText('No fuel records yet')).toBeVisible({ timeout: 10000 })
  })
})
