import { test, expect } from '@playwright/test'

test.describe('P0 foundation', () => {
  test('applies the stored accent before React mounts', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('accent', 'amber')
      localStorage.setItem('theme', 'dark')
    })
    // Block the JS bundle so only the inline script has run.
    await page.route('**/assets/*.js', (route) => route.abort())
    await page.goto('/')

    const accent = await page.evaluate(() =>
      document.documentElement.style.getPropertyValue('--accent').trim(),
    )
    // constants/accents.ts ACCENTS.amber.accent — see accent-contrast.test.ts
    // drift test, which pins this file's hexes to that module.
    expect(accent).toBe('#f9aa0b')
  })

  test('applies the stored theme class before React mounts', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('theme', 'light'))
    await page.route('**/assets/*.js', (route) => route.abort())
    await page.goto('/')
    await expect(page.locator('html')).toHaveClass(/light/)
  })
})
