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

/**
 * Opens the dashboard in a language. The fixture pins 'en' in localStorage, and
 * useLanguageSync swaps in the saved account language once the app loads, so
 * wait for html lang rather than lean on init-script order.
 */
async function openDashboard(page: Page, request: APIRequestContext, lang: Lang): Promise<void> {
  await setLanguage(request, lang)
  await page.goto('/')
  await expect(page.locator('html')).toHaveAttribute('lang', lang, { timeout: 15000 })
}

interface CaptionScan {
  /** Expected captions this card didn't show, so nothing got measured for them. */
  missing: string[]
  problems: string[]
}

// The card shows year, make and model, not the nickname, so it's found by its VIN.
let seededVin = ''

/**
 * The seeded car's four stat-tile captions, checked word by word.
 *
 * Every expected caption has to be there, or it's reported missing. The words
 * are walked across text nodes, so a caption split inside an inline child is
 * still measured. A word on more than one line got broken, and a word past
 * the tile's padding spilled out.
 */
async function scanCaptions(page: Page, labels: string[]): Promise<CaptionScan> {
  return page.evaluate(async ({ wanted, vin }) => {
    await document.fonts.ready
    const problems: string[] = []
    // The biggest box around one set of tiles is that vehicle's card.
    const card = [...document.querySelectorAll<HTMLElement>('main [data-testid="vehicle-stat-tiles"]')]
      .map((tiles) => {
        let box = tiles
        while (box.parentElement && box.parentElement.querySelectorAll('[data-testid="vehicle-stat-tiles"]').length === 1) box = box.parentElement
        return { tiles, box }
      })
      .find(({ box }) => (box.textContent ?? '').includes(vin))?.tiles
    const found = new Set<string>()
    for (const tile of card?.querySelectorAll<HTMLElement>('.rounded-tile') ?? []) {
      const caption = tile.lastElementChild as HTMLElement | null
      if (!caption) continue
      // Every text node under the caption, with where each one starts in the whole.
      const pieces: { node: Text; start: number }[] = []
      let text = ''
      const walker = document.createTreeWalker(caption, NodeFilter.SHOW_TEXT)
      for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
        pieces.push({ node, start: text.length })
        text += node.data
      }
      if (!wanted.includes(text.trim())) continue
      found.add(text.trim())
      const at = (offset: number, end: boolean): [Text, number] => {
        const piece = [...pieces].reverse().find((p) => (end ? p.start < offset : p.start <= offset))!
        return [piece.node, offset - piece.start]
      }
      // The caption div always fills the tile, so measure the words themselves
      // against the tile's content box. A nowrap or truncated caption spills here.
      const t = tile.getBoundingClientRect()
      const style = getComputedStyle(tile)
      const inner = { left: t.left + parseFloat(style.paddingLeft), right: t.right - parseFloat(style.paddingRight) }
      for (const match of text.matchAll(/\S+/g)) {
        const range = document.createRange()
        range.setStart(...at(match.index, false))
        range.setEnd(...at(match.index + match[0].length, true))
        // Pieces of one word in two inline nodes give two rects on one line, so count lines.
        const rects = [...range.getClientRects()].filter((r) => r.width > 0).sort((a, b) => a.top - b.top)
        let lines = 0
        let bottom = -Infinity
        for (const r of rects) {
          if (r.top >= bottom - 1) lines += 1
          bottom = Math.max(bottom, r.bottom)
        }
        if (lines !== 1) problems.push(`"${match[0]}" in "${text.trim()}" sits on ${lines} lines`)
        const w = range.getBoundingClientRect()
        if (w.left < inner.left - 0.5 || w.right > inner.right + 0.5) {
          problems.push(`"${match[0]}" in "${text.trim()}" spills out of its tile (${w.left.toFixed(1)}..${w.right.toFixed(1)} vs ${inner.left.toFixed(1)}..${inner.right.toFixed(1)})`)
        }
      }
    }
    return { missing: wanted.filter((label) => !found.has(label.trim())), problems }
  }, { wanted: labels, vin: seededVin })
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
  seededVin = await ledger.vehicle({
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
        // Wait for the seeded card to land with all four captions.
        await expect
          .poll(async () => (await scanCaptions(page, labels)).missing, { timeout: 15000 })
          .toEqual([])
        const scan = await scanCaptions(page, labels)
        for (const label of scan.missing) failures.push(`${width}px: "${label}" was never measured`)
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
