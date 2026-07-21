import { test, expect } from './helpers/fixtures'
import { nav } from './helpers/selectors'
import { TEST_VEHICLE } from './helpers/seed'
import { familyLoads, trackWoff2Requests } from './helpers/fonts'

/**
 * Prefixed (subpath) E2E — issue #107.
 *
 * Runs ONLY under the `subpath` Playwright project, whose baseURL is
 * `http://127.0.0.1:3001/mygarage/`. That URL points at a prefix-stripping
 * proxy (`e2e/subpath-proxy.mjs`) in front of the backend serving the
 * production `dist` build with `MYGARAGE_ROOT_PATH=/mygarage`. So every
 * assertion here exercises the real subpath request path: browser -> proxy
 * (strip `/mygarage`) -> backend `<base href="/mygarage/">` injection -> SPA.
 *
 * NOTE: `dashboard.spec.ts` / `navigation.spec.ts` etc. assert `toHaveURL('/')`
 * style ROOT-relative paths and run under the `chromium` (root, Vite dev)
 * project — they are intentionally excluded from this project via
 * `testIgnore`, and this file is the only one the `subpath` project runs.
 */

const PREFIX = '/mygarage'

test.describe('Subpath hosting (/mygarage)', () => {
  test('shell + hashed assets load under the prefix', async ({ page }) => {
    // Track the entry-script request so we prove assets resolve under /mygarage/
    // (the exact failure mode a missing <base href> would cause: a deep-route
    // reload fetching /mygarage/vehicles/assets/... and 404-ing).
    const assetUrls: string[] = []
    page.on('response', (resp) => {
      const u = resp.url()
      if (u.includes('/assets/') && u.endsWith('.js')) assetUrls.push(u)
    })

    await page.goto('.')
    await expect(nav.dashboard(page)).toBeVisible({ timeout: 15000 })

    // The backend-injected <base href> anchors every relative URL at the prefix.
    const baseHref = await page.evaluate(
      () => document.querySelector('base')?.getAttribute('href') ?? null,
    )
    expect(baseHref).toBe(`${PREFIX}/`)

    // At least one hashed entry chunk was fetched from under the prefix.
    expect(assetUrls.some((u) => u.includes(`${PREFIX}/assets/`))).toBeTruthy()
  })

  test('deep-link reload serves the SPA (not a 404)', async ({ page }) => {
    // baseURL-relative -> http://127.0.0.1:3001/mygarage/vehicles/<vin>
    await page.goto(`vehicles/${TEST_VEHICLE.vin}`)
    // A hard reload of a nested route must still boot the SPA via <base href>.
    await page.reload()
    await expect(
      page.getByRole('heading', { name: TEST_VEHICLE.nickname }),
    ).toBeVisible({ timeout: 15000 })
    expect(page.url()).toContain(`${PREFIX}/vehicles/${TEST_VEHICLE.vin}`)
  })

  test('an API call succeeds through the proxy', async ({ page, request }) => {
    // request fixture is baseURL-relative -> .../mygarage/api/vehicles
    const resp = await request.get('api/vehicles')
    expect(resp.ok(), `GET api/vehicles -> ${resp.status()}`).toBeTruthy()
    const body = await resp.json()
    const vins = (Array.isArray(body) ? body : (body.items ?? body.vehicles ?? [])).map(
      (v: { vin?: string }) => v.vin,
    )
    expect(vins).toContain(TEST_VEHICLE.vin)

    // And the app itself renders data fetched via withBase('/api') axios calls.
    await page.goto('.')
    await expect(
      page.getByText(`${TEST_VEHICLE.year} ${TEST_VEHICLE.make} ${TEST_VEHICLE.model}`),
    ).toBeVisible({ timeout: 15000 })
  })

  test('a vehicle photo <img> loads under the prefix', async ({ page }) => {
    await page.goto('.')
    await expect(nav.dashboard(page)).toBeVisible({ timeout: 15000 })

    // The seeded main photo renders via withBase('/api/vehicles/.../photos/..').
    const img = page.locator('img[src*="/api/vehicles/"]').first()
    await expect(img).toBeVisible({ timeout: 15000 })

    const src = await img.getAttribute('src')
    expect(src, 'photo src should be prefixed').toContain(`${PREFIX}/api/vehicles/`)

    // The image actually decoded (proxy served the binary, media route worked).
    await expect
      .poll(async () => img.evaluate((el: HTMLImageElement) => el.naturalWidth), {
        timeout: 15000,
      })
      .toBeGreaterThan(0)
  })

  test('a chart renders under the prefix (Recharts url(#id) clip-paths)', async ({ page }) => {
    await page.goto('.')
    await nav.analytics(page).click()
    await expect(page).toHaveURL(new RegExp(`${PREFIX}/analytics$`), { timeout: 15000 })

    // Seeded fuel cost -> garage analytics renders at least one Recharts SVG.
    const surface = page.locator('svg.recharts-surface').first()
    await expect(surface).toBeVisible({ timeout: 20000 })

    // The injected <base href> must NOT have broken SVG fragment refs: Recharts
    // emits <clipPath id="..."> referenced by clip-path: url(#...). If <base>
    // had rebased the fragment the clipPath def would be absent/orphaned.
    const clipDefs = await page.locator('svg.recharts-surface clipPath').count()
    expect(clipDefs).toBeGreaterThan(0)
  })

  test.describe('Fonts under the prefix', () => {
    // Task 11 added font coverage to foundation.spec.ts, but that file runs
    // ONLY under the `chromium` project (root, Vite dev server) — nothing
    // exercised font resolution through the /mygarage prefix, which is
    // exactly the scenario src/styles/fonts.css's own doc comment warns
    // about: a font referenced from public/ (Vite copies public/ verbatim,
    // unprefixed) 404s under the #107 subpath proxy, and `font-display: swap`
    // falls back to system-ui *silently*. These two tests are the subpath
    // analogue of the foundation.spec.ts P0 exit-criteria font tests, reusing
    // the same helpers (see e2e/helpers/fonts.ts for why a bare
    // `document.fonts.check()` and a plain status check are both insufficient).
    test('both font families actually load', async ({ page }) => {
      await page.goto('.')
      await page.waitForLoadState('networkidle')

      expect(
        await familyLoads(page, 'Inter Variable'),
        'Inter did not load under the /mygarage prefix',
      ).toBe(true)
      expect(
        await familyLoads(page, 'JetBrains Mono Variable'),
        'JetBrains Mono did not load under the /mygarage prefix',
      ).toBe(true)
    })

    test('font files resolve under the prefix, not an HTML fallback', async ({ page }) => {
      const { seen, bad } = trackWoff2Requests(page)
      await page.goto('.')
      await page.waitForLoadState('networkidle')

      // Prove the observer actually saw font traffic — see fonts.ts doc
      // comment. Without this, a font moved to public/ (which starts
      // returning 404 -> HTML under the prefix) wouldn't even register a
      // .woff2 request in some browsers' font-matching short-circuits, and
      // an empty `bad` would pass for the wrong reason.
      expect(seen.length, 'no .woff2 requests were observed at all').toBeGreaterThan(0)
      // Every observed font request actually resolved under the prefix
      // (not e.g. an unprefixed /fonts/x.woff2 that happened to 200 against
      // something else entirely).
      for (const url of seen) {
        expect(url, `.woff2 request should resolve under ${PREFIX}`).toContain(`${PREFIX}/`)
      }
      expect(bad).toEqual([])
    })
  })

  test.describe('PWA runtime', () => {
    test('service worker registers with a /mygarage/ scope', async ({ page }) => {
      await page.goto('.')
      await expect(nav.dashboard(page)).toBeVisible({ timeout: 15000 })

      // SW registration happens on window "load"; poll until it appears.
      const scope = await page
        .waitForFunction(
          async () => {
            const reg = await navigator.serviceWorker.getRegistration()
            return reg?.scope ?? null
          },
          null,
          { timeout: 20000 },
        )
        .then((h) => h.jsonValue())

      expect(scope, 'SW scope should be prefixed').toMatch(new RegExp(`${PREFIX}/$`))
    })

    test('manifest + start_url resolve under the prefix', async ({ page, request }) => {
      await page.goto('.')

      // The manifest <link> resolves to an absolute URL under the prefix.
      const manifestHref = await page.evaluate(() => {
        const link = document.querySelector<HTMLLinkElement>('link[rel="manifest"]')
        return link ? link.href : null
      })
      expect(manifestHref).not.toBeNull()
      expect(new URL(manifestHref as string).pathname).toBe(`${PREFIX}/manifest.json`)

      // It actually serves, and its relative start_url resolves under prefix.
      const resp = await request.get('manifest.json')
      expect(resp.ok(), `GET manifest.json -> ${resp.status()}`).toBeTruthy()
      const manifest = await resp.json()
      const resolvedStart = new URL(manifest.start_url, manifestHref as string)
      expect(resolvedStart.pathname.startsWith(`${PREFIX}/`)).toBeTruthy()
    })

    test('offline fallback serves under the prefix (no root-relative cache miss)', async ({
      page,
      context,
    }) => {
      // Prime the SW: wait until it controls the page.
      await page.goto('.')
      await page.waitForFunction(
        async () => {
          const reg = await navigator.serviceWorker.getRegistration()
          return !!reg?.active
        },
        null,
        { timeout: 20000 },
      )
      // Give the SW a beat to claim the client, then reload so it controls us.
      await page.reload()
      await page.waitForFunction(() => !!navigator.serviceWorker.controller, null, {
        timeout: 20000,
      })

      // Go offline and navigate to a fresh route: the SW must serve the cached
      // shell or offline.html — both live under /mygarage/, so a root-relative
      // cache key would miss here.
      await context.setOffline(true)
      try {
        const resp = await page.goto(`vehicles/${TEST_VEHICLE.vin}`, {
          waitUntil: 'domcontentloaded',
        })
        // Served from SW (2xx), not a network error page.
        expect(resp?.status() ?? 0).toBeLessThan(400)
        const html = await page.content()
        expect(html.length).toBeGreaterThan(0)
      } finally {
        await context.setOffline(false)
      }
    })
  })
})
