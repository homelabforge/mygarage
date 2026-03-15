import { test, expect } from '@playwright/test'
import { TEST_VEHICLE } from './helpers/selectors'

/**
 * Vehicle detail tab navigation tests.
 *
 * Verifies that each primary tab and its sub-tabs load without errors.
 * Uses the seeded TEST_VEHICLE from global.setup.ts.
 */
test.describe('Vehicle Detail — Tab Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`/vehicles/${TEST_VEHICLE.vin}`)
    await expect(
      page.getByRole('heading', { name: TEST_VEHICLE.nickname })
    ).toBeVisible({ timeout: 15000 })
  })

  test('Overview tab loads by default with vehicle info', async ({ page }) => {
    // Overview is the default active tab
    const overviewTab = page.getByRole('tab', { name: 'Overview' })
    await expect(overviewTab).toBeVisible()
    await expect(overviewTab).toHaveAttribute('aria-selected', 'true')

    // Basic Information section should be visible
    await expect(page.getByText('Basic Information')).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('Purchase Information')).toBeVisible()
  })

  test('Media tab — Photos sub-tab loads', async ({ page }) => {
    await page.getByRole('tab', { name: 'Media' }).click()

    // Photos sub-tab should be the default
    await expect(page.getByRole('tab', { name: 'Photos' })).toBeVisible({ timeout: 5000 })
    await expect(page.getByRole('tab', { name: 'Documents' })).toBeVisible()

    // No error banner should appear
    await expect(page.locator('[data-sonner-toast][data-type="error"]')).not.toBeVisible({ timeout: 2000 })
  })

  test('Media tab — switch to Documents sub-tab', async ({ page }) => {
    await page.getByRole('tab', { name: 'Media' }).click()
    await page.getByRole('tab', { name: 'Documents' }).click()

    // Should not show errors
    await expect(page.locator('[data-sonner-toast][data-type="error"]')).not.toBeVisible({ timeout: 2000 })
  })

  test('Maintenance tab — cycles through sub-tabs', async ({ page }) => {
    await page.getByRole('tab', { name: 'Maintenance' }).click()

    // Default sub-tab should be Service
    const serviceTab = page.getByRole('tab', { name: 'Service' })
    await expect(serviceTab).toBeVisible({ timeout: 5000 })

    // Cycle through visible sub-tabs
    const subTabs = ['Service', 'Fuel', 'Odometer', 'Recalls']
    for (const tabName of subTabs) {
      const tab = page.getByRole('tab', { name: tabName })
      // Tab might not exist for non-motorized vehicles — skip if not visible
      if (await tab.isVisible()) {
        await tab.click()
        // Give content time to render, no error toast
        await page.waitForTimeout(500)
        await expect(page.locator('[data-sonner-toast][data-type="error"]')).not.toBeVisible({ timeout: 2000 })
      }
    }
  })

  test('Tracking tab — Notes and Reports sub-tabs load', async ({ page }) => {
    await page.getByRole('tab', { name: 'Tracking' }).click()

    // Notes is the default
    await expect(page.getByRole('tab', { name: 'Notes' })).toBeVisible({ timeout: 5000 })

    // Switch to Reports
    await page.getByRole('tab', { name: 'Reports' }).click()
    await expect(page.locator('[data-sonner-toast][data-type="error"]')).not.toBeVisible({ timeout: 2000 })
  })

  test('Financial tab — cycles through sub-tabs', async ({ page }) => {
    await page.getByRole('tab', { name: 'Financial' }).click()

    const subTabs = ['Warranties', 'Insurance', 'Tax & Registration', 'Tolls']
    for (const tabName of subTabs) {
      const tab = page.getByRole('tab', { name: tabName })
      if (await tab.isVisible()) {
        await tab.click()
        await page.waitForTimeout(500)
        await expect(page.locator('[data-sonner-toast][data-type="error"]')).not.toBeVisible({ timeout: 2000 })
      }
    }
  })

  test('switching between primary tabs preserves page stability', async ({ page }) => {
    const primaryTabs = ['Media', 'Maintenance', 'Tracking', 'Financial', 'Overview']

    for (const tabName of primaryTabs) {
      await page.getByRole('tab', { name: tabName }).click()
      // Each tab switch should not cause a page crash or error
      await page.waitForTimeout(300)
      // The vehicle nickname should still be visible in the header
      await expect(
        page.getByRole('heading', { name: TEST_VEHICLE.nickname })
      ).toBeVisible()
    }
  })

  test('navigates to vehicle detail via URL tab parameter', async ({ page }) => {
    // Navigate with ?tab=fuel to go directly to Maintenance > Fuel
    await page.goto(`/vehicles/${TEST_VEHICLE.vin}?tab=fuel`)
    await expect(
      page.getByRole('heading', { name: TEST_VEHICLE.nickname })
    ).toBeVisible({ timeout: 15000 })

    // Fuel sub-tab should be active
    await expect(page.getByText('Fuel History')).toBeVisible({ timeout: 10000 })
  })

  test('navigates to vehicle detail via URL tab=insurance', async ({ page }) => {
    await page.goto(`/vehicles/${TEST_VEHICLE.vin}?tab=insurance`)
    await expect(
      page.getByRole('heading', { name: TEST_VEHICLE.nickname })
    ).toBeVisible({ timeout: 15000 })

    // Insurance sub-tab should be active under Financial
    const insuranceTab = page.getByRole('tab', { name: 'Insurance' })
    await expect(insuranceTab).toBeVisible({ timeout: 5000 })
    await expect(insuranceTab).toHaveAttribute('aria-selected', 'true')
  })
})
