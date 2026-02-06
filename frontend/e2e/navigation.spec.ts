import { test, expect } from '@playwright/test'
import { nav } from './helpers/selectors'

test.describe('Navigation', () => {
  test('desktop nav bar has all expected links', async ({ page }) => {
    await page.goto('/')
    await expect(nav.dashboard(page)).toBeVisible({ timeout: 15000 })
    await expect(nav.analytics(page)).toBeVisible()
    await expect(nav.addressBook(page)).toBeVisible()
    await expect(nav.calendar(page)).toBeVisible()
  })

  test('navigates between pages via nav links', async ({ page }) => {
    await page.goto('/')
    await expect(nav.dashboard(page)).toBeVisible({ timeout: 15000 })

    await nav.analytics(page).click()
    await expect(page).toHaveURL('/analytics', { timeout: 10000 })

    await nav.calendar(page).click()
    await expect(page).toHaveURL('/calendar', { timeout: 10000 })

    await nav.dashboard(page).click()
    await expect(page).toHaveURL('/', { timeout: 10000 })
  })
})
