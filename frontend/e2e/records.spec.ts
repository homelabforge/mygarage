import { test, expect } from '@playwright/test'
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

    // Fill in the form fields
    const today = new Date().toISOString().split('T')[0]
    await page.locator('#date').fill(today)
    await page.locator('#gallons').fill('12.5')
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
    await page.locator('#mileage').fill('50000')
    await page.locator('#gallons').fill('15.0')
    await page.locator('#price_per_unit').fill('3.50')

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
})
