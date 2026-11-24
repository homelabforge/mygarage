import { test, expect, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import { adminSessionFromStorageState } from './helpers/seed'

const API_BASE = 'http://localhost:8686/api'
/** Mirrors `global.setup.ts`'s `AUTH_FILE`: the session the setup project saved. */
const AUTH_FILE = './e2e/.auth/user.json'

/**
 * Language and currency are each person's own, and live in Quick Settings (the
 * gear). The drawer marks the app behind it `aria-hidden`, so a test that reads
 * the nav closes the drawer first.
 *
 * @param page The page under test.
 * @returns The open drawer.
 */
async function openQuickSettings(page: Page): Promise<Locator> {
  await page.goto('/')
  await page.getByRole('button', { name: 'Quick settings' }).click()
  const drawer = page.getByRole('dialog', { name: 'Quick settings' })
  await expect(drawer).toBeVisible({ timeout: 15000 })
  return drawer
}

/**
 * Put the admin's language back to English through the API.
 *
 * Through the session the setup project saved, never a fresh login:
 * `/api/auth/login` allows five a minute per IP, the whole suite shares one
 * address, and a reset that 429s leaves the account in Polish for every spec
 * after this one (see `adminSessionFromStorageState`).
 *
 * @param request The API request context.
 */
async function resetLanguage(request: APIRequestContext): Promise<void> {
  const admin = await adminSessionFromStorageState(request, API_BASE, AUTH_FILE)
  const reset = await request.put(`${API_BASE}/auth/me`, {
    data: { language: 'en' },
    headers: admin.headers,
  })
  expect(reset.ok(), `Language reset failed: ${reset.status()}`).toBeTruthy()
}

/**
 * Polish never fits the top bar, so its links fold behind the menu button.
 * Checks that it did fold, then opens it so the links can be read.
 */
async function openFoldedNav(page: Page): Promise<void> {
  const burger = page.locator('[data-nav="hamburger"]')
  await expect(burger).toBeVisible({ timeout: 10000 })
  await burger.click()
}

test.describe('Internationalization', () => {
  // Reset language to English via API after each test to prevent DB contamination
  test.afterEach(async ({ request }) => {
    await resetLanguage(request)
  })

  test('language selector in Quick Settings switches nav labels', async ({ page, request }) => {
    const drawer = await openQuickSettings(page)

    const languageSelect = drawer.locator('select').filter({ has: page.locator('option[value="pl"]') })
    await expect(languageSelect).toBeVisible()
    await expect(languageSelect).toHaveValue('en')

    await languageSelect.selectOption('pl')
    await page.keyboard.press('Escape')

    // Nav labels should change to Polish
    await openFoldedNav(page)
    await expect(page.getByRole('link', { name: 'Panel sterowania' })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('link', { name: 'Analityka' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Kalendarz' })).toBeVisible()

    // Back to English through the account, not the drawer: the gear's own
    // label is translated too, so a Polish page has no stable name to click.
    await resetLanguage(request)
    await page.reload()
    await expect(page.getByRole('link', { name: 'Dashboard' })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('link', { name: 'Analytics' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Calendar' })).toBeVisible()
  })

  test('currency selector in Quick Settings shows a preview', async ({ page }) => {
    const drawer = await openQuickSettings(page)

    const currencySelect = drawer.locator('select').filter({ has: page.locator('option[value="EUR"]') })
    await expect(currencySelect).toBeVisible()
    await expect(currencySelect).toHaveValue('USD')
    await expect(drawer.getByText(/Preview:.*\$/)).toBeVisible()
  })

  test('language persists across page refresh', async ({ page }) => {
    const drawer = await openQuickSettings(page)

    const languageSelect = drawer.locator('select').filter({ has: page.locator('option[value="pl"]') })
    await languageSelect.selectOption('pl')
    await page.keyboard.press('Escape')
    await openFoldedNav(page)
    await expect(page.getByRole('link', { name: 'Panel sterowania' })).toBeVisible({ timeout: 10000 })

    await page.reload()

    // Polish persists: it was saved to the account. The afterEach resets it.
    await openFoldedNav(page)
    await expect(page.getByRole('link', { name: 'Panel sterowania' })).toBeVisible({ timeout: 15000 })
  })

  test('html lang attribute updates on language change', async ({ page }) => {
    const drawer = await openQuickSettings(page)

    // Default should be en
    await expect(page.locator('html')).toHaveAttribute('lang', 'en')

    // Switch to Polish. Found by its options, not through the drawer: the
    // drawer's own name turns Polish too ("Szybkie ustawienia").
    await expect(drawer).toBeVisible()
    const languageSelect = page.locator('select').filter({ has: page.locator('option[value="pl"]') })
    await languageSelect.selectOption('pl')
    await expect(page.locator('html')).toHaveAttribute('lang', 'pl', { timeout: 5000 })

    // Switch back
    await languageSelect.selectOption('en')
    await expect(page.locator('html')).toHaveAttribute('lang', 'en', { timeout: 5000 })
  })
})
