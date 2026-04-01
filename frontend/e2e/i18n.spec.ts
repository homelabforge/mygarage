import { test, expect } from './helpers/fixtures'

const API_BASE = 'http://localhost:8686/api'
const ADMIN = { username: 'e2e-admin', password: 'E2eTest!ng123' }

test.describe('Internationalization', () => {
  // Reset language to English via API after each test to prevent DB contamination
  test.afterEach(async ({ request }) => {
    const loginResp = await request.post(`${API_BASE}/auth/login`, {
      data: ADMIN,
    })
    if (loginResp.ok()) {
      const loginData = await loginResp.json()
      await request.put(`${API_BASE}/auth/me`, {
        data: { language: 'en' },
        headers: {
          Cookie: `mygarage_token=${loginData.access_token}`,
          'X-CSRF-Token': loginData.csrf_token,
        },
      })
    }
  })

  test('language selector exists in settings and switches nav labels', async ({ page }) => {
    await page.goto('/settings')

    // Wait for settings page to load
    await expect(page.getByText('System Configuration')).toBeVisible({ timeout: 15000 })

    // Language selector should be visible
    const languageSelect = page.locator('select').filter({ has: page.locator('option[value="pl"]') })
    await expect(languageSelect).toBeVisible()

    // Verify default is English
    await expect(languageSelect).toHaveValue('en')

    // Switch to Polish
    await languageSelect.selectOption('pl')

    // Nav labels should change to Polish
    await expect(page.getByRole('link', { name: 'Panel główny' })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('link', { name: 'Analityka' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Kalendarz' })).toBeVisible()

    // Switch back to English
    await languageSelect.selectOption('en')

    // Nav labels should revert to English
    await expect(page.getByRole('link', { name: 'Dashboard' })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('link', { name: 'Analytics' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Calendar' })).toBeVisible()
  })

  test('currency selector exists and shows preview', async ({ page }) => {
    await page.goto('/settings')

    // Wait for settings page to load
    await expect(page.getByText('System Configuration')).toBeVisible({ timeout: 15000 })

    // Currency selector should be visible
    const currencySelect = page.locator('select').filter({ has: page.locator('option[value="EUR"]') })
    await expect(currencySelect).toBeVisible()

    // Verify default is USD
    await expect(currencySelect).toHaveValue('USD')

    // Preview should show USD formatting
    await expect(page.getByText(/Preview:.*\$/)).toBeVisible()
  })

  test('language persists across page refresh', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByText('System Configuration')).toBeVisible({ timeout: 15000 })

    // Switch to Polish
    const languageSelect = page.locator('select').filter({ has: page.locator('option[value="pl"]') })
    await languageSelect.selectOption('pl')

    // Wait for Polish nav to render
    await expect(page.getByRole('link', { name: 'Panel główny' })).toBeVisible({ timeout: 10000 })

    // Refresh page
    await page.reload()

    // Polish should persist via localStorage
    await expect(page.getByRole('link', { name: 'Panel główny' })).toBeVisible({ timeout: 15000 })

    // Clean up: switch back to English
    const langSelectAfterReload = page.locator('select').filter({ has: page.locator('option[value="pl"]') })
    await langSelectAfterReload.selectOption('en')
    await expect(page.getByRole('link', { name: 'Dashboard' })).toBeVisible({ timeout: 10000 })
  })

  test('html lang attribute updates on language change', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByText('System Configuration')).toBeVisible({ timeout: 15000 })

    // Default should be en
    await expect(page.locator('html')).toHaveAttribute('lang', 'en')

    // Switch to Polish
    const languageSelect = page.locator('select').filter({ has: page.locator('option[value="pl"]') })
    await languageSelect.selectOption('pl')

    // html lang should update
    await expect(page.locator('html')).toHaveAttribute('lang', 'pl', { timeout: 5000 })

    // Switch back
    await languageSelect.selectOption('en')
    await expect(page.locator('html')).toHaveAttribute('lang', 'en', { timeout: 5000 })
  })
})
