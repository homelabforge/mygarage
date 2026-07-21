import { test, expect } from '@playwright/test'

// Block every script request by RESOURCE TYPE, not URL glob. A glob like
// '**/assets/*.js' only matches a preview/production build's output path —
// under the `chromium` project's dev-server webServer (`bun run dev`), the
// bundle is served as /src/main.tsx and /node_modules/.vite/deps/*.js, so
// that glob matches zero of the ~90 requests a real page load makes and
// React mounts fully while the test still passes. Filtering by
// resourceType() === 'script' works regardless of dev-vs-preview URL shapes.
async function blockScripts(page: import('@playwright/test').Page): Promise<void> {
  await page.route('**/*', (route) =>
    route.request().resourceType() === 'script' ? route.abort() : route.continue(),
  )
}

test.describe('P0 foundation', () => {
  test('applies the stored accent before React mounts', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('accent', 'amber')
      localStorage.setItem('theme', 'dark')
    })
    await blockScripts(page)
    await page.goto('/')

    // Prove scripts were actually blocked, in THIS spec — if React mounted
    // (it renders children into #root), this test is silently measuring
    // ThemeProvider's own class/property writes instead of the inline
    // script, and must fail rather than pass by coincidence.
    const rootChildren = await page.locator('#root').evaluate((el) => el.childElementCount)
    expect(rootChildren).toBe(0)

    const accent = await page.evaluate(() =>
      document.documentElement.style.getPropertyValue('--accent').trim(),
    )
    // constants/accents.ts ACCENTS.amber.accent — see accent-contrast.test.ts
    // drift test, which pins this file's hexes to that module.
    expect(accent).toBe('#f9aa0b')
  })

  test('applies the stored theme class before React mounts', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('theme', 'light'))
    await blockScripts(page)
    await page.goto('/')

    const rootChildren = await page.locator('#root').evaluate((el) => el.childElementCount)
    expect(rootChildren).toBe(0)

    await expect(page.locator('html')).toHaveClass(/light/)
  })
})
