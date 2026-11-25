import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { request as apiRequest, type APIRequestContext, type Page } from '@playwright/test'

import { test, expect } from './helpers/fixtures'
import { adminSessionFromStorageState, randomVin, seedLedger, type SeedLedger } from './helpers/seed'

/**
 * Dashboard stat tiles never split a word (Task 10).
 *
 * Four tiles across leave each caption about 50px at phone widths, and Polish
 * PRZYPOMNIENIA needs 92. overflow-wrap:anywhere then breaks it mid-word. The
 * grid goes 2x2 below a measured container width instead, and jsdom has no
 * layout, so only a real browser can check it.
 */

const ROOT_BASE_URL = 'http://localhost:3000'
const API_BASE = `${ROOT_BASE_URL}/api`
const AUTH_FILE = './e2e/.auth/user.json'
const HERE = path.dirname(fileURLToPath(import.meta.url))

/** Mirrors the @min-[488px] in VehicleStatisticsCard. */
const THRESHOLD = 488

const LANGS = ['en', 'pl', 'de', 'ru', 'uk', 'fr', 'it', 'ms', 'pt-BR'] as const
const WIDTHS = [320, 390, 768, 1024, 1440] as const
const KEYS = ['service', 'fuel', 'maintenance', 'docs'] as const

type Lang = (typeof LANGS)[number]

/** The four tile captions in a language, read from the shipped locale files. */
function captionsFor(lang: Lang): string[] {
  const file = lang === 'en'
    ? path.resolve(HERE, '../src/locales/en/vehicles.json')
    : path.resolve(HERE, `../public/locales/${lang}/vehicles.json`)
  const stats = (JSON.parse(readFileSync(file, 'utf8')) as { vehicleStats: Record<string, string> }).vehicleStats
  return KEYS.map((key) => stats[key])
}

/** Sets the account's language; useLanguageSync applies it on the next load. */
async function setLanguage(request: APIRequestContext, language: string): Promise<void> {
  const admin = await adminSessionFromStorageState(request, API_BASE, AUTH_FILE)
  const res = await request.put(`${API_BASE}/auth/me`, { data: { language }, headers: admin.headers })
  expect(res.ok(), `Language ${language} failed: ${res.status()}`).toBeTruthy()
}

/** Opens the dashboard in a language, with that language's first paint. */
async function openDashboard(page: Page, request: APIRequestContext, lang: Lang): Promise<void> {
  await setLanguage(request, lang)
  // Runs after the fixture's 'en' pin, so it wins.
  await page.addInitScript((value) => localStorage.setItem('i18nextLng', value), lang)
  await page.goto('/')
  await expect(page.locator('html')).toHaveAttribute('lang', lang, { timeout: 15000 })
}

interface CaptionScan {
  count: number
  problems: string[]
}

/**
 * Every stat-tile caption on the page, checked word by word.
 *
 * A word whose Range comes back as two rects got broken across lines, and a
 * word past the tile's padding spilled out. Tiles are found by caption text,
 * not the test id, so this runs on any build.
 */
async function scanCaptions(page: Page, labels: string[]): Promise<CaptionScan> {
  return page.evaluate(async (wanted) => {
    await document.fonts.ready
    const problems: string[] = []
    let count = 0
    for (const tile of document.querySelectorAll<HTMLElement>('main .rounded-tile')) {
      const caption = tile.lastElementChild as HTMLElement | null
      const node = caption?.firstChild
      if (!caption || !node || node.nodeType !== Node.TEXT_NODE) continue
      const text = node.textContent ?? ''
      if (!wanted.includes(text.trim())) continue
      count += 1
      // The caption div always fills the tile, so measure the words themselves
      // against the tile's content box. A nowrap or truncated caption spills here.
      const t = tile.getBoundingClientRect()
      const style = getComputedStyle(tile)
      const inner = { left: t.left + parseFloat(style.paddingLeft), right: t.right - parseFloat(style.paddingRight) }
      for (const match of text.matchAll(/\S+/g)) {
        const range = document.createRange()
        range.setStart(node, match.index)
        range.setEnd(node, match.index + match[0].length)
        const rects = range.getClientRects().length
        if (rects !== 1) problems.push(`"${match[0]}" in "${text.trim()}" spans ${rects} rects`)
        const w = range.getBoundingClientRect()
        if (w.left < inner.left - 0.5 || w.right > inner.right + 0.5) {
          problems.push(`"${match[0]}" in "${text.trim()}" spills out of its tile (${w.left.toFixed(1)}..${w.right.toFixed(1)} vs ${inner.left.toFixed(1)}..${inner.right.toFixed(1)})`)
        }
      }
    }
    return { count, problems }
  }, labels)
}

/** Pins the tile container's width and counts the grid's tracks. */
async function tracksAt(page: Page, width: number): Promise<number> {
  return page.getByTestId('vehicle-stat-tiles').first().evaluate((el, w) => {
    el.style.width = `${w}px`
    const grid = el.firstElementChild as HTMLElement
    return getComputedStyle(grid).gridTemplateColumns.trim().split(/\s+/).length
  }, width)
}

let api: APIRequestContext
let ledger: SeedLedger
let adminId: number

test.beforeAll(async () => {
  api = await apiRequest.newContext({ baseURL: ROOT_BASE_URL })
  const admin = await adminSessionFromStorageState(api, API_BASE, AUTH_FILE)
  ledger = seedLedger(api, API_BASE, admin.headers)
  const me = await api.get(`${API_BASE}/auth/me`, { headers: admin.headers })
  expect(me.ok(), `auth/me: ${me.status()}`).toBeTruthy()
  adminId = (await me.json()).id as number
  await ledger.vehicle({
    vin: randomVin('TILE'),
    nickname: 'E2E Tile Car',
    vehicle_type: 'Car',
    year: 2011,
    make: 'TileRigMake',
    model: 'TileRigModel',
  })
})

test.afterAll(async () => {
  try {
    await ledger?.cleanup()
  } finally {
    await api?.dispose()
  }
})

test.describe('Dashboard stat tiles', () => {
  // The Vite dev server's React Query devtools toggle pokes past the right
  // edge at phone widths. Prod doesn't ship it (same as page-fit.spec.ts).
  // Under 768px the Quick Entry gate bounces "/" off the dashboard, even on a
  // resize. Its own session flag lets it fall through, same as tapping Dashboard.
  test.beforeEach(async ({ page }) => {
    await page.addInitScript((id) => {
      sessionStorage.setItem(`qe_redirected:${id}`, '1')
      document.addEventListener('DOMContentLoaded', () => {
        const style = document.createElement('style')
        style.textContent = '.tsqd-parent-container { display: none !important; }'
        document.head.append(style)
      })
    }, adminId)
  })

  test.afterEach(async ({ request }) => {
    await setLanguage(request, 'en')
  })

  for (const lang of LANGS) {
    test(`no caption word splits in ${lang}`, async ({ page, request }) => {
      const labels = captionsFor(lang)
      await openDashboard(page, request, lang)
      const failures: string[] = []
      for (const width of WIDTHS) {
        await page.setViewportSize({ width, height: 900 })
        // Wait for the cards to land before the first scan.
        await expect
          .poll(async () => (await scanCaptions(page, labels)).count, { timeout: 15000 })
          .toBeGreaterThan(0)
        const scan = await scanCaptions(page, labels)
        for (const problem of scan.problems) failures.push(`${width}px: ${problem}`)
      }
      expect(failures, failures.join('\n')).toEqual([])
    })
  }

  for (const lang of ['en', 'pl'] as const) {
    test(`2 tracks below ${THRESHOLD}px, 4 at ${THRESHOLD}px, in ${lang}`, async ({ page, request }) => {
      await page.setViewportSize({ width: 1440, height: 900 })
      await openDashboard(page, request, lang)
      await expect(page.getByTestId('vehicle-stat-tiles').first()).toBeVisible({ timeout: 15000 })
      expect(await tracksAt(page, THRESHOLD - 1)).toBe(2)
      expect(await tracksAt(page, THRESHOLD)).toBe(4)
    })
  }

  test('the dashboard fits a 320px phone', async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 844 })
    await page.goto('/')
    await expect(page.locator('main .rounded-tile').first()).toBeVisible({ timeout: 15000 })
    await page.waitForLoadState('networkidle')
    const { scrollWidth, clientWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }))
    expect(scrollWidth, `page is ${scrollWidth}px wide on a ${clientWidth}px screen`).toBeLessThanOrEqual(clientWidth)
  })
})
