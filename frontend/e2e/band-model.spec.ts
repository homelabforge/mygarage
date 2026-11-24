import type { APIRequestContext, Page } from '@playwright/test'
import { test, expect } from './helpers/fixtures'
import { adminSessionFromStorageState } from './helpers/seed'

const API_BASE = 'http://localhost:8686/api'
const AUTH_FILE = './e2e/.auth/user.json'

/** Sets the account's language; useLanguageSync applies it on the next load. */
async function setLanguage(request: APIRequestContext, language: string): Promise<void> {
  const admin = await adminSessionFromStorageState(request, API_BASE, AUTH_FILE)
  const res = await request.put(`${API_BASE}/auth/me`, { data: { language }, headers: admin.headers })
  expect(res.ok(), `Language ${language} failed: ${res.status()}`).toBeTruthy()
}

/**
 * P2 hardening — the shell's final-review Important
 * (.superpowers/sdd/p2-hardening-brief.md). jsdom applies no CSS, so every
 * unit test in this codebase can only assert a class STRING, never computed
 * display. That blind spot let a cascade-tie bug ship TWICE inside P2: an
 * IconButton's base `inline-flex` defeats a bare `hidden` at Tailwind v4's
 * fixed base-utility source order (see p2-implementer-standing.md), so a
 * band class that reads correctly in the DOM can render visible at every
 * width anyway. Only a real browser measuring `getComputedStyle().display`
 * catches it — this spec is that guard.
 *
 * The five affordances are matched by attribute selectors, which match
 * regardless of visibility (unlike `getByRole`, which drops display:none nodes
 * from the accessibility tree, the exact blind spot this spec exists to
 * close). The links and the hamburger carry `data-nav`, since their classes
 * change when the links don't fit.
 *
 * Note: `locator.evaluate` / `page.$$eval` below are Playwright's browser-context
 * script-execution APIs (they run a function inside the page, matching the
 * house pattern in e2e/foundation.spec.ts) — not JavaScript's global `eval()`.
 */

const SELECTORS = {
  inlineNav: '[data-nav="links"]',
  hamburger: '[data-nav="hamburger"]',
  search: '[class~="max-nav:hidden"]',
  gear: 'button[aria-label="Quick settings"]',
  bottomBar: 'nav[class~="md:hidden"]',
} as const

type Affordance = keyof typeof SELECTORS

// The three mutually-exclusive PRIMARY navs (LOCKED model: exactly one per
// width). Search and gear are aux controls — covered by the truth table
// below but excluded from the "exactly one" cross-check.
const PRIMARY_NAVS: Affordance[] = ['inlineNav', 'hamburger', 'bottomBar']

interface BandRow {
  width: number
  inlineNav: boolean
  hamburger: boolean
  search: boolean
  gear: boolean
  bottomBar: boolean
}

// The band truth table (brief). 767/768 and 899/900 are the exact off-by-one
// boundaries where `max-md`/`max-nav` and `md`/`nav` flip — the danger
// points, so all six widths are tested, not just four.
//
// The gear (Quick Settings) is visible at EVERY width: it is the only path to
// the per-account accent picker and logout below 768px, so it must not drop on
// phone (P10 mobile account access — see the logout reachability test below).
//
// From 900 up the inline links show only once they fit: English needs about
// 1164px, so 900 and 1000 still use the hamburger (search moves to the bar at
// 900 either way).
const BAND_TABLE: BandRow[] = [
  { width: 375, inlineNav: false, hamburger: false, search: false, gear: true, bottomBar: true },
  { width: 767, inlineNav: false, hamburger: false, search: false, gear: true, bottomBar: true },
  { width: 768, inlineNav: false, hamburger: true, search: false, gear: true, bottomBar: false },
  { width: 899, inlineNav: false, hamburger: true, search: false, gear: true, bottomBar: false },
  { width: 900, inlineNav: false, hamburger: true, search: true, gear: true, bottomBar: false },
  { width: 1000, inlineNav: false, hamburger: true, search: true, gear: true, bottomBar: false },
  { width: 1320, inlineNav: true, hamburger: false, search: true, gear: true, bottomBar: false },
]

/** Computed display, or "hidden" when the node is laid out but invisible (the links that don't fit). */
async function readDisplay(page: Page, key: Affordance): Promise<string> {
  return page.locator(SELECTORS[key]).evaluate((el) => {
    const style = getComputedStyle(el)
    return style.visibility === 'hidden' ? 'hidden' : style.display
  })
}

// The e2e admin's avatar, badge and logout take about 140px of the bar, which
// leaves English only ~7px to spare at 1320. These tests are about which nav
// shows, not about the account block, so take it out of the measurement.
async function hideAccountBlock(page: Page): Promise<void> {
  await page.addStyleTag({ content: '[data-nav-cluster] [class~="border-l"] { display: none !important; }' })
}

const isShown = (display: string): boolean => display !== 'none' && display !== 'hidden'

/** How far the page scrolls sideways, 0 when it doesn't. */
async function sidewaysScroll(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
}

test.describe('P2 band model', () => {
  test('exactly one primary nav is visible per width; aux controls match the truth table', async ({
    page,
  }) => {
    await page.goto('/')
    // Width-independent readiness: the shell header exists at every
    // viewport, so this doesn't race the desktop-only inline nav.
    await page.waitForSelector('header')
    await hideAccountBlock(page)

    // Vacuous-pass guard (brief): each selector must resolve to exactly one
    // element BEFORE any band assertion runs, so a renamed/removed
    // affordance fails loudly here instead of quietly reading `none`
    // because the node is absent rather than hidden.
    for (const key of Object.keys(SELECTORS) as Affordance[]) {
      await expect(
        page.locator(SELECTORS[key]),
        `${key} selector (${SELECTORS[key]}) must resolve to exactly one element`,
      ).toHaveCount(1)
    }

    // The hamburger menu is intentionally never opened here — an open panel
    // re-renders a second stacked nav + search field and would pollute
    // every measurement below (brief).
    for (const row of BAND_TABLE) {
      await page.setViewportSize({ width: row.width, height: 900 })

      const displays: Record<Affordance, string> = {
        inlineNav: await readDisplay(page, 'inlineNav'),
        hamburger: await readDisplay(page, 'hamburger'),
        search: await readDisplay(page, 'search'),
        gear: await readDisplay(page, 'gear'),
        bottomBar: await readDisplay(page, 'bottomBar'),
      }

      for (const key of Object.keys(SELECTORS) as Affordance[]) {
        const expectedVisible = row[key]
        const isVisible = isShown(displays[key])
        expect(
          isVisible,
          `${row.width}px ${key}: expected ${expectedVisible ? 'visible' : 'hidden'}, got display="${displays[key]}"`,
        ).toBe(expectedVisible)
      }
      expect(await sidewaysScroll(page), `${row.width}px: the page scrolls sideways`).toBe(0)

      const visiblePrimaries = PRIMARY_NAVS.filter((key) => isShown(displays[key]))
      expect(
        visiblePrimaries.length,
        `${row.width}px: expected exactly ONE primary nav visible, got ${visiblePrimaries.length} (${
          visiblePrimaries.join(', ') || 'none'
        })`,
      ).toBe(1)
    }
  })
})

test.describe('Top links that do not fit', () => {
  const primaries = async (page: Page): Promise<string[]> => {
    const shown: string[] = []
    for (const key of PRIMARY_NAVS) if (isShown(await readDisplay(page, key))) shown.push(key)
    return shown
  }

  test('the links come back when the window grows, and nothing scrolls sideways on the way', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('header')
    await hideAccountBlock(page)
    for (const [width, nav] of [[1320, 'inlineNav'], [1000, 'hamburger'], [1320, 'inlineNav'], [900, 'hamburger']] as const) {
      await page.setViewportSize({ width, height: 900 })
      await expect.poll(() => primaries(page), `${width}px`).toEqual([nav])
      expect(await sidewaysScroll(page), `${width}px`).toBe(0)
    }
  })

  test('a longer language folds the links into the hamburger at the same width', async ({ page, request }) => {
    try {
      await page.setViewportSize({ width: 1320, height: 900 })
      await page.goto('/')
      await page.waitForSelector('header')
      await hideAccountBlock(page)
      await expect.poll(() => primaries(page)).toEqual(['inlineNav'])
      // Polish needs more room than the bar ever has. The account's language
      // wins over localStorage, so set it there (same as page-fit.spec.ts).
      await setLanguage(request, 'pl')
      await page.reload()
      await page.waitForSelector('header')
      await hideAccountBlock(page)
      await expect(page.locator('html')).toHaveAttribute('lang', 'pl')
      await expect.poll(() => primaries(page)).toEqual(['hamburger'])
      expect(await sidewaysScroll(page)).toBe(0)
    } finally {
      await setLanguage(request, 'en')
    }
  })
})

test.describe('P10 mobile account access', () => {
  // The Quick Settings gear is visible at phone width (band table above), and it is the
  // ONLY route to logout and the accent picker below 768px. Prove the full logout path
  // works there — a jsdom unit test can assert the drawer's row but never that the gear
  // is reachable at 375px. e2e auth is local + signed in (seed.ts), so the row renders.
  //
  // The journey is deliberately the REAL one, not a shortcut to "/". `User.
  // mobile_quick_entry_enabled` defaults to True, so on a phone a fresh session is
  // redirected off "/" to /quick-entry by MobileQuickEntryGate — which renders a minimal
  // header with no gear and no logout. Tapping "Dashboard" there is therefore the only
  // route a phone user has to logout, and it works because QuickEntry sets the
  // `qe_redirected:<id>` session flag on mount, which lets the gate fall through.
  // Driving that path also covers the escape hatch itself: if the flag or the Dashboard
  // link ever broke, a phone user would be trapped on /quick-entry with no way to sign
  // out, and this is the only test that would catch it. Going straight to "/" instead
  // races the redirect — the click lands, then the gate unmounts the whole shell and the
  // Logout button detaches mid-click.
  test('logout is reachable via Quick Settings at phone width', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 900 })
    await page.goto('/')

    // Phone + fresh session ⇒ the gate MUST bounce us to Quick Entry.
    await page.waitForURL('**/quick-entry')
    await page.getByRole('link', { name: 'Dashboard' }).click()
    await expect(page).toHaveURL(/\/$/)
    await page.waitForSelector('header')

    const gear = page.getByRole('button', { name: 'Quick settings' })
    await expect(gear).toBeVisible()
    await gear.click()

    await expect(page.getByRole('dialog', { name: 'Quick settings' })).toBeVisible()
    const logout = page.getByRole('button', { name: 'Logout' })
    await expect(logout).toBeVisible()
    await logout.click()

    await expect(page).toHaveURL(/\/login/)
  })
})

test.describe('P2 motion tokens', () => {
  test('every ui-motion element uses the pinned duration + easing tokens', async ({ page }) => {
    await page.goto('/__ui')
    // Must FAIL, not skip, if the dev gallery never renders at all.
    await expect(
      page.locator('[class*="ui-motion"]').first(),
      '/__ui (dev gallery) did not render a single ui-motion element',
    ).toBeVisible({ timeout: 15000 })

    const population = await page.locator('[class*="ui-motion"]').count()
    console.log(`ui-motion population: ${population}`)
    expect(
      population,
      'zero ui-motion elements found — selector or /__ui route is broken',
    ).toBeGreaterThan(0)

    const swept = await page.$$eval('[class*="ui-motion"]', (elements) => {
      // A multi-value transition splits on TOP-LEVEL commas only. Timing
      // functions like `cubic-bezier(0, 0, 0.2, 1)` carry their own commas, so
      // a naive `.split(',')` would shatter one value into "cubic-bezier(0",
      // "0", … . Split on commas that are not inside parentheses (CSS timing
      // functions never nest parens, so this lookahead is exact for them).
      const splitTop = (value: string): string[] =>
        value.split(/,(?![^(]*\))/).map((part) => part.trim())
      return elements.map((el) => {
        const style = getComputedStyle(el)
        return {
          cls: el.getAttribute('class') ?? '',
          durations: splitTop(style.transitionDuration),
          timings: splitTop(style.transitionTimingFunction),
        }
      })
    })

    // Pinned tokens (index.css `--duration-fast` / `--duration-toggle` /
    // `--ease-standard`, P1 Task 26). No element's duration part may be
    // '0s' and no timing part may be 'ease'/'linear'/foreign — that would be
    // a native-transition collision. This falls out of the two `every`-part
    // assertions below: neither value is in the pinned sets.
    const PINNED_DURATIONS = new Set(['0.15s', '0.18s'])
    const PINNED_TIMING = 'cubic-bezier(0, 0, 0.2, 1)'

    for (const { cls, durations, timings } of swept) {
      for (const duration of durations) {
        expect(
          PINNED_DURATIONS.has(duration),
          `"${cls}" has transition-duration part "${duration}" — expected one of 0.15s/0.18s (native-transition collision or --duration-fast drift)`,
        ).toBe(true)
      }
      for (const timing of timings) {
        expect(
          timing,
          `"${cls}" has transition-timing-function part "${timing}" — expected ${PINNED_TIMING} (ease-standard)`,
        ).toBe(PINNED_TIMING)
      }
    }
  })
})
