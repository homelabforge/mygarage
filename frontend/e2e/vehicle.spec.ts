import { test, expect } from '@playwright/test'

test.describe('Vehicle Management', () => {
  test('add vehicle button opens modal', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('button', { name: /add vehicle/i })).toBeVisible({
      timeout: 15000,
    })

    await page.getByRole('button', { name: /add vehicle/i }).click()

    // The add vehicle wizard should appear with a VIN input step
    await expect(page.getByText('Enter VIN')).toBeVisible({ timeout: 10000 })
  })

  test('vehicle detail page shows 404 for nonexistent VIN', async ({ page }) => {
    await page.goto('/vehicles/NONEXISTENT1234567')

    // Should show error or not found state
    await expect(
      page.getByText(/not found|error|failed/i)
    ).toBeVisible({ timeout: 15000 })
  })
})
