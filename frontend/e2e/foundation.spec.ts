import { test, expect } from './helpers/fixtures'
import type { Page } from '@playwright/test'
import { ACCENTS, DEFAULT_ACCENT } from '../src/constants/accents'

// Block every script request by RESOURCE TYPE, not URL glob. A glob like
// '**/assets/*.js' only matches a preview/production build's output path —
// under the `chromium` project's dev-server webServer (`bun run dev`), the
// bundle is served as /src/main.tsx and /node_modules/.vite/deps/*.js, so
// that glob matches zero of the ~90 requests a real page load makes and
// React mounts fully while the test still passes. Filtering by
// resourceType() === 'script' works regardless of dev-vs-preview URL shapes.
async function blockScripts(page: Page): Promise<void> {
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

/** '#4f8cff' -> 'rgb(79, 140, 255)', matching getComputedStyle's canonical form. */
function hexToRgb(hex: string): string {
  const h = hex.replace('#', '')
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgb(${r}, ${g}, ${b})`
}

/** Drops a fresh `.bg-primary` element into the page and reads its resolved paint. */
async function paintBgPrimary(page: Page): Promise<string> {
  await page.evaluate(() => {
    const el = document.createElement('div')
    el.className = 'bg-primary'
    el.id = 'accent-probe'
    document.body.appendChild(el)
  })
  return page.locator('#accent-probe').evaluate((el) => getComputedStyle(el).backgroundColor)
}

/**
 * Resolves whether a font family actually loads — NOT via
 * `document.fonts.check()` alone. That method has two failure modes here:
 * it reflects only whether a font happens to already be in use on the
 * current DOM (Dashboard renders no monospace text, so JetBrains Mono stays
 * 'unloaded' regardless of whether the asset works), AND — verified by
 * temporarily deleting the font import while writing this test — it
 * returns `true` when ZERO `@font-face` rules match the family at all,
 * because there is trivially nothing "pending". So this filters
 * `document.fonts` down to faces that actually declare the family, fails
 * outright if that set is empty, then calls `.load()` on each match and
 * requires every one to reach `status === 'loaded'`.
 */
async function familyLoads(page: Page, family: string): Promise<boolean> {
  return page.evaluate(async (fam) => {
    const matches = [...document.fonts].filter(
      (f) => f.family.replace(/^["']|["']$/g, '') === fam,
    )
    if (matches.length === 0) return false
    await Promise.all(matches.map((f) => f.load()))
    return matches.every((f) => f.status === 'loaded')
  }, family)
}

test.describe('P0 exit criteria', () => {
  test('JetBrains Mono actually loads', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    const loaded = await familyLoads(page, 'JetBrains Mono Variable')
    expect(loaded, 'JetBrains Mono did not load — check the subset imports').toBe(true)
  })

  test('Inter actually loads', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    expect(await familyLoads(page, 'Inter Variable')).toBe(true)
  })

  test('font files are served, not 404', async ({ page }) => {
    const seen: string[] = []
    const bad: string[] = []
    page.on('response', (r) => {
      if (!r.url().endsWith('.woff2')) return
      seen.push(r.url())
      // NOT a plain !r.ok() check. Verified while writing this test: both the
      // Vite dev server (SPA history fallback) and the production backend's
      // custom_404_handler (backend/app/main.py) return 200 + text/html for
      // ANY unmatched path, including a broken /assets/*.woff2 reference —
      // confirmed by requesting a deliberately nonexistent .woff2 path and
      // getting back 200 OK. So a status-only check can never observe this
      // failure here: the browser would silently receive an HTML document,
      // fail to parse it as a font, and fall back to a system font — exactly
      // the silent failure src/styles/fonts.css exists to prevent. Checking
      // content-type catches it instead.
      const contentType = r.headers()['content-type'] ?? ''
      if (r.status() !== 200 || !contentType.startsWith('font/')) {
        bad.push(`${r.status()} ${contentType} ${r.url()}`)
      }
    })
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // Prove the observer actually saw font traffic. Without this, a build that
    // stops requesting fonts entirely (e.g. the CSS @import got dropped) would
    // leave `bad` empty too, and the assertion below would pass for the wrong
    // reason — the exact vacuous-pass shape this phase already hit once with a
    // URL-glob script blocker that matched nothing.
    expect(seen.length, 'no .woff2 requests were observed at all').toBeGreaterThan(0)
    expect(bad).toEqual([])
  })

  test('switching accent repaints a bg-primary element, not just a focus ring', async ({
    page,
  }) => {
    // Any element carrying bg-primary. If the accent vars were ever set on a
    // descendant instead of document.documentElement, @theme's
    // `--color-primary: var(--accent)` (resolved against :root) would keep
    // rendering the OLD accent here while raw --accent* consumers (focus
    // rings, glows) switched correctly — a partial, silent failure. Assert on
    // the resolved paint, never on the --accent custom property's value.
    await page.goto('/')
    const before = await paintBgPrimary(page)
    expect(before, 'default accent (blue) did not resolve through bg-primary').toBe(
      hexToRgb(ACCENTS[DEFAULT_ACCENT].accent),
    )

    await page.evaluate(() => localStorage.setItem('accent', 'amber'))
    await page.reload()
    const after = await paintBgPrimary(page)

    expect(
      after,
      'bg-primary did not follow the accent — the accent vars are probably not on documentElement',
    ).toBe(hexToRgb(ACCENTS.amber.accent))
    expect(after).not.toBe(before)
  })

  test('no console errors on any top-level route', async ({ page }) => {
    const errors: string[] = []
    page.on('console', (m) => {
      if (m.type() === 'error') errors.push(m.text())
    })
    page.on('pageerror', (e) => errors.push(String(e)))

    const routes = [
      '/',
      '/analytics',
      '/address-book',
      '/supplies',
      '/poi-finder',
      '/calendar',
      '/settings',
      '/about',
    ]
    for (const route of routes) {
      await page.goto(route)
      await page.waitForLoadState('networkidle')
    }
    expect(errors).toEqual([])
  })
})
