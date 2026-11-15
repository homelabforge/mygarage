import type { APIRequestContext, Page } from '@playwright/test'
import { test, expect } from './helpers/fixtures'
import { adminSessionFromStorageState } from './helpers/seed'
import { TEST_VEHICLE } from './helpers/selectors'

const API_BASE = 'http://localhost:8686/api'
const AUTH_FILE = './e2e/.auth/user.json'

/**
 * PAGE-fit: no page is wider than a phone (#298).
 *
 * A header that can't wrap pushes the page past the screen edge. The phone
 * then lays the page out wider and taller than what's visible, so a drawer's
 * full-height panel runs off the bottom and takes its Save button with it.
 * jsdom has no layout, so only a real browser can catch this.
 *
 * Russian runs too: its labels are the longest, and most of the headers fixed
 * in #298 only overflowed in a longer language.
 */

const WIDTH = 360

const VEHICLE_TABS = [
  'overview', 'documents', 'service', 'odometer', 'tires', 'brakes', 'recalls', 'fuel', 'notes',
  'reminders', 'reports', 'warranties', 'insurance', 'tax', 'tolls', 'financing', 'suppliesused',
]

const ROUTES = [
  '/supplies', '/analytics', '/calendar', '/address-book', '/insurance', '/poi-finder', '/settings',
  '/about', `/vehicles/${TEST_VEHICLE.vin}/analytics`,
  ...VEHICLE_TABS.map((tab) => `/vehicles/${TEST_VEHICLE.vin}?tab=${tab}`),
]

/** What sticks out past the right edge, outermost only, skipping anything an ancestor already clips. */
async function overflowOf(page: Page): Promise<string | null> {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth
    const sw = document.documentElement.scrollWidth
    if (sw <= vw) return null
    const offenders: string[] = []
    for (const el of document.querySelectorAll<HTMLElement>('body *')) {
      const rect = el.getBoundingClientRect()
      if (rect.width === 0 || rect.right <= vw + 1) continue
      if ((el.parentElement?.getBoundingClientRect().right ?? 0) > vw + 1) continue
      let clipped = false
      for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
        if (getComputedStyle(a).overflowX !== 'visible' && a.getBoundingClientRect().right <= vw + 1) {
          clipped = true
          break
        }
      }
      if (clipped) continue
      offenders.push(`<${el.tagName.toLowerCase()}> "${(el.textContent ?? '').trim().slice(0, 40)}" ends at ${Math.round(rect.right)}px`)
    }
    return `page is ${sw}px wide: ${offenders.slice(0, 3).join('; ') || 'no single offender found'}`
  })
}

async function expectRoutesFit(page: Page): Promise<void> {
  await page.setViewportSize({ width: WIDTH, height: 800 })
  const failures: string[] = []
  for (const route of ROUTES) {
    await page.goto(route)
    await page.waitForLoadState('networkidle')
    await expect(page.locator('main')).toBeVisible({ timeout: 15000 })
    const overflow = await overflowOf(page)
    if (overflow) failures.push(`${route}: ${overflow}`)
  }
  expect(failures, failures.join('\n')).toEqual([])
}

/** Sets the account's language; useLanguageSync applies it on the next load. */
async function setLanguage(request: APIRequestContext, language: string): Promise<void> {
  const admin = await adminSessionFromStorageState(request, API_BASE, AUTH_FILE)
  const res = await request.put(`${API_BASE}/auth/me`, { data: { language }, headers: admin.headers })
  expect(res.ok(), `Language ${language} failed: ${res.status()}`).toBeTruthy()
}

test.describe('PAGE-fit phone width', () => {
  test.setTimeout(180_000)

  // e2e runs the Vite dev server, whose React Query devtools toggle pokes a
  // few px past the right edge. Prod builds don't ship it (see nav-fit.spec.ts).
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      document.addEventListener('DOMContentLoaded', () => {
        const style = document.createElement('style')
        style.textContent = '.tsqd-parent-container { display: none !important; }'
        document.head.append(style)
      })
    })
  })

  test(`every page fits a ${WIDTH}px phone`, async ({ page }) => {
    await expectRoutesFit(page)
  })

  test(`every page fits a ${WIDTH}px phone in Russian`, async ({ page, request }) => {
    try {
      await setLanguage(request, 'ru')
      // Runs after the fixture's 'en' pin, so first paint is already Russian.
      await page.addInitScript(() => localStorage.setItem('i18nextLng', 'ru'))
      await expectRoutesFit(page)
      await expect(page.locator('html')).toHaveAttribute('lang', 'ru')
    } finally {
      await setLanguage(request, 'en')
    }
  })
})
