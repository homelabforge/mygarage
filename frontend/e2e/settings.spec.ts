import { test, expect } from './helpers/fixtures'

test.describe('Settings', () => {
  test('settings page loads', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByRole('heading', { name: /settings/i })).toBeVisible({
      timeout: 15000,
    })
  })

  test('settings page has theme section', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByText('Theme', { exact: true })).toBeVisible({ timeout: 15000 })
  })
})
