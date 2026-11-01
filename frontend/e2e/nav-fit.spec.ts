import type { APIRequestContext, Page } from '@playwright/test'
import { test, expect } from './helpers/fixtures'
import { adminSessionFromStorageState } from './helpers/seed'

const API_BASE = 'http://localhost:8686/api'
const AUTH_FILE = './e2e/.auth/user.json'

/**
 * NAV-fit: the phone tab bar fits a phone. Eight tabs used to need 464px at
 * minimum, so at 360 Home and Settings sat fully off-screen. jsdom has no
 * layout, so only a real browser can measure this.
 *
 * Starts on /supplies, not "/": on a phone, "/" bounces to /quick-entry,
 * which has no tab bar (see band-model.spec.ts).
 */

const PHONES = [360, 390]

/** Every bar item sits inside the viewport on one line, and the row doesn't overflow. */
async function expectBarFits(page: Page, width: number): Promise<void> {
  const bar = page.locator('nav[data-tab-bar]')
  await expect(bar).toBeVisible()
  const items = bar.locator('a, button')
  await expect(items).toHaveCount(5)

  const height = page.viewportSize()?.height ?? 0
  expect(height).toBeGreaterThan(0)
  for (let i = 0; i < 5; i++) {
    const item = items.nth(i)
    const name = (await item.textContent()) ?? `item ${i}`
    const box = await item.boundingBox()
    expect(box, `${width}px ${name}: no box`).not.toBeNull()
    if (!box) continue
    expect(box.x, `${width}px ${name}: starts off the left edge`).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width, `${width}px ${name}: runs off the right edge`).toBeLessThanOrEqual(width)
    expect(box.y + box.height, `${width}px ${name}: below the screen`).toBeLessThanOrEqual(height)

    const lines = await item.locator('span').evaluate((span) => {
      const lineHeight = Number.parseFloat(getComputedStyle(span).lineHeight)
      return span.getBoundingClientRect().height / lineHeight
    })
    expect(lines, `${width}px ${name}: label wraps`).toBeLessThan(1.5)
  }

  const row = await bar.locator('> div').evaluate((el) => ({
    scrollWidth: el.scrollWidth,
    clientWidth: el.clientWidth,
  }))
  expect(row.scrollWidth, `${width}px: the row overflows`).toBeLessThanOrEqual(row.clientWidth)
}

/** Back to English through the account (same as i18n.spec.ts). */
async function resetLanguage(request: APIRequestContext): Promise<void> {
  const admin = await adminSessionFromStorageState(request, API_BASE, AUTH_FILE)
  const reset = await request.put(`${API_BASE}/auth/me`, {
    data: { language: 'en' },
    headers: admin.headers,
  })
  expect(reset.ok(), `Language reset failed: ${reset.status()}`).toBeTruthy()
}

test.describe('NAV-fit phone tab bar', () => {
  for (const width of PHONES) {
    test(`fits a ${width}px phone`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 })
      await page.goto('/supplies')
      await expectBarFits(page, width)
    })
  }

  test('More opens the rest and its links navigate', async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 800 })
    await page.goto('/supplies')

    const more = page.locator('nav[data-tab-bar]').getByRole('button', { name: 'More' })
    await more.click()
    const sheet = page.getByRole('dialog', { name: 'More' })
    await expect(sheet).toBeVisible()
    for (const name of ['Contacts', 'Insurance', 'POI', 'Settings']) {
      await expect(sheet.getByRole('link', { name })).toBeVisible()
    }

    await sheet.getByRole('link', { name: 'Settings' }).click()
    await expect(page).toHaveURL(/\/settings$/)
    await expect(sheet).toBeHidden()
    await expect(more).toHaveClass(/bg-\(--accent-soft\)/)
  })

  // Polish has the longest labels ("Materiały eksploatacyjne" used to wrap to
  // two lines and spill out of the bar).
  test('fits a 360px phone in Polish', async ({ page, request }) => {
    try {
      await page.setViewportSize({ width: 360, height: 800 })
      await page.goto('/supplies')
      await page.getByRole('button', { name: 'Quick settings' }).click()
      const drawer = page.getByRole('dialog', { name: 'Quick settings' })
      await expect(drawer).toBeVisible({ timeout: 15000 })
      await drawer.locator('select').filter({ has: page.locator('option[value="pl"]') }).selectOption('pl')
      await page.keyboard.press('Escape')
      await expect(drawer).toBeHidden()

      const bar = page.locator('nav[data-tab-bar]')
      await expect(bar.getByRole('link', { name: 'Materiały eksploatacyjne' })).toBeVisible({ timeout: 10000 })
      await expect(bar.getByRole('button', { name: 'Więcej' })).toBeVisible()
      await expectBarFits(page, 360)
    } finally {
      await resetLanguage(request)
    }
  })
})
