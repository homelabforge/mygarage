import type { Page } from '@playwright/test'
import { test, expect } from './helpers/fixtures'

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
 * The five affordances are matched by `[class~="token"]` attribute
 * selectors, which match regardless of visibility (unlike `getByRole`,
 * which drops display:none nodes from the accessibility tree — the exact
 * blind spot this spec exists to close).
 *
 * Note: `locator.evaluate` / `page.$$eval` below are Playwright's browser-context
 * script-execution APIs (they run a function inside the page, matching the
 * house pattern in e2e/foundation.spec.ts) — not JavaScript's global `eval()`.
 */

const SELECTORS = {
  inlineNav: 'nav[class~="nav:flex"]',
  hamburger: '[class~="nav:hidden"]',
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
// boundaries where `max-md`/`md` and `max-nav`/`nav` flip — the danger
// points, so all six widths are tested, not just four.
const BAND_TABLE: BandRow[] = [
  { width: 375, inlineNav: false, hamburger: false, search: false, gear: false, bottomBar: true },
  { width: 767, inlineNav: false, hamburger: false, search: false, gear: false, bottomBar: true },
  { width: 768, inlineNav: false, hamburger: true, search: false, gear: true, bottomBar: false },
  { width: 899, inlineNav: false, hamburger: true, search: false, gear: true, bottomBar: false },
  { width: 900, inlineNav: true, hamburger: false, search: true, gear: true, bottomBar: false },
  { width: 1320, inlineNav: true, hamburger: false, search: true, gear: true, bottomBar: false },
]

/** Reads computed `display` for one affordance at the current viewport. */
async function readDisplay(page: Page, key: Affordance): Promise<string> {
  return page.locator(SELECTORS[key]).evaluate((el) => getComputedStyle(el).display)
}

test.describe('P2 band model', () => {
  test('exactly one primary nav is visible per width; aux controls match the truth table', async ({
    page,
  }) => {
    await page.goto('/')
    // Width-independent readiness: the shell header exists at every
    // viewport, so this doesn't race the desktop-only inline nav.
    await page.waitForSelector('header')

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
        const isVisible = displays[key] !== 'none'
        expect(
          isVisible,
          `${row.width}px ${key}: expected ${expectedVisible ? 'visible' : 'display:none'}, got display="${displays[key]}"`,
        ).toBe(expectedVisible)
      }

      const visiblePrimaries = PRIMARY_NAVS.filter((key) => displays[key] !== 'none')
      expect(
        visiblePrimaries.length,
        `${row.width}px: expected exactly ONE primary nav visible, got ${visiblePrimaries.length} (${
          visiblePrimaries.join(', ') || 'none'
        })`,
      ).toBe(1)
    }
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
