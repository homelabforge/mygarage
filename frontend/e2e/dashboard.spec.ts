import { test, expect } from '@playwright/test'
import { nav } from './helpers/selectors'

test.describe('Dashboard', () => {
  test('loads dashboard page', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: /garage/i })).toBeVisible({
      timeout: 15000,
    })
  })

  test('shows add vehicle button', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('button', { name: /add vehicle/i })).toBeVisible({
      timeout: 15000,
    })
  })

  test('navigates to analytics', async ({ page }) => {
    await page.goto('/')
    await nav.analytics(page).click()
    await expect(page).toHaveURL('/analytics', { timeout: 10000 })
  })
})
