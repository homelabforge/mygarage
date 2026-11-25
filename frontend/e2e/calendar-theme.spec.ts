import { inflateSync } from 'node:zlib'

import { request as apiRequest, type APIRequestContext, type Page } from '@playwright/test'

import { test, expect } from './helpers/fixtures'
import { adminSessionFromStorageState, randomVin, seedLedger, type SeedLedger } from './helpers/seed'

/**
 * The calendar follows a live theme switch (G2a-22).
 *
 * The vitest half pins that setTheme reaches the one mounted Schedule-X app.
 * This half is what a person sees: the chrome and an event repaint both ways,
 * the date picker popup (its own isDark, never synced by setTheme) reads right
 * through the bridge, and the view and date survive because nothing remounts.
 */

const ROOT_BASE_URL = 'http://localhost:3000'
const API_BASE = `${ROOT_BASE_URL}/api`
const AUTH_FILE = './e2e/.auth/user.json'

const TITLE = 'E2E Theme Reminder'
const DAY = 86_400_000
const NOTES = 'Theme check notes.'

/** Chart slot 1 per theme, which --color-cal-maintenance aliases. */
const CAL_MAINTENANCE = { dark: '#3987e5', light: '#2a78d6' }
const CAL_TYPES = ['maintenance', 'insurance', 'warranty', 'service'] as const

let api: APIRequestContext
let ledger: SeedLedger

test.beforeAll(async () => {
  api = await apiRequest.newContext({ baseURL: ROOT_BASE_URL })
  const admin = await adminSessionFromStorageState(api, API_BASE, AUTH_FILE)
  ledger = seedLedger(api, API_BASE, admin.headers)
  const vin = await ledger.vehicle({
    vin: randomVin('THEM'),
    nickname: 'E2E Theme Car',
    vehicle_type: 'Car',
    year: 2003,
    make: 'ThemeRigMake',
    model: 'ThemeRigModel',
  })
  // Yesterday, today and tomorrow in UTC: whatever the household zone, one of
  // them is its today, so the current week always shows one.
  for (const offset of [-1, 0, 1]) {
    await ledger.post(`/vehicles/${vin}/reminders`, {
      title: `${TITLE} ${offset + 1}`,
      reminder_type: 'date',
      due_date: new Date(Date.now() + offset * DAY).toISOString().split('T')[0],
      // Tomorrow is in the upcoming list in any zone, so it carries the notes.
      ...(offset === 1 ? { notes: NOTES } : {}),
    })
  }
})

test.afterAll(async () => {
  try {
    await ledger?.cleanup()
  } finally {
    await api?.dispose()
  }
})

type Theme = 'light' | 'dark'

async function currentTheme(page: Page): Promise<Theme> {
  return page.evaluate(() => (document.documentElement.classList.contains('light') ? 'light' : 'dark'))
}

/** What a CSS colour expression computes to here, in Chrome's own serialisation. */
async function computed(page: Page, expression: string): Promise<string> {
  return page.evaluate((value) => {
    const probe = document.createElement('div')
    probe.style.backgroundColor = value
    document.body.appendChild(probe)
    const out = getComputedStyle(probe).backgroundColor
    probe.remove()
    return out
  }, expression)
}

/** WCAG contrast of two CSS colours, flattened to sRGB through a canvas. */
async function contrast(page: Page, fg: string, bg: string): Promise<number> {
  return page.evaluate(
    ([a, b]) => {
      const ctx = document.createElement('canvas').getContext('2d')!
      const lum = (colour: string): number => {
        ctx.clearRect(0, 0, 1, 1)
        ctx.fillStyle = colour
        ctx.fillRect(0, 0, 1, 1)
        const [r, g, bl] = [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3).map((v) => {
          const c = v / 255
          return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
        })
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl
      }
      const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
      return (hi + 0.05) / (lo + 0.05)
    },
    [fg, bg] as const,
  )
}

interface Snapshot {
  theme: Theme
  view: string
  range: string
  chrome: string
  event: string
}

async function snapshot(page: Page): Promise<Snapshot> {
  const event = page.locator('.sx__date-grid-event', { hasText: TITLE }).first()
  await expect(event).toBeVisible({ timeout: 15000 })
  return {
    theme: await currentTheme(page),
    view: ((await page.locator('.sx__view-selection-selected-item').textContent()) ?? '').trim(),
    range: ((await page.locator('.sx__range-heading').textContent()) ?? '').trim(),
    chrome: await page.locator('.sx__calendar').evaluate((el) => getComputedStyle(el).backgroundColor),
    event: await event.evaluate((el) => getComputedStyle(el).backgroundColor),
  }
}

async function flipTheme(page: Page, to: Theme): Promise<void> {
  const saved = page.waitForResponse((r) => r.url().endsWith('/api/auth/me') && r.request().method() === 'PUT')
  await page.getByRole('button', { name: 'Toggle theme' }).click()
  await expect.poll(() => currentTheme(page)).toBe(to)
  await saved
}

/** The tokens behind what's on screen, for the theme that's on now. */
async function expectThemed(page: Page, shot: Snapshot): Promise<void> {
  expect(shot.chrome).toBe(await computed(page, 'var(--color-surface)'))
  expect(shot.event).toBe(await computed(page, 'var(--color-cal-maintenance-container)'))
  const main = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue('--color-cal-maintenance').trim(),
  )
  expect(main).toBe(CAL_MAINTENANCE[shot.theme])
}

/** The header date picker's popup reads this theme's surface, whatever its own isDark says. */
async function expectPopupThemed(page: Page): Promise<void> {
  await page.locator('.sx__date-input').click()
  const popup = page.locator('.sx__date-picker-popup')
  await expect(popup).toBeVisible()
  const background = await popup.evaluate((el) => getComputedStyle(el).backgroundColor)
  const allowed = [await computed(page, 'var(--color-surface)'), await computed(page, 'var(--color-surface-3)')]
  expect(allowed).toContain(background)
  const text = await popup.evaluate((el) => getComputedStyle(el).color)
  expect(text).toBe(await computed(page, 'var(--color-text)'))
  await page.locator('.sx__date-input').click()
  await expect(popup).toBeHidden()
}

test('a theme switch repaints the mounted calendar both ways and keeps its view and date', async ({ page }) => {
  await page.goto('/calendar')
  await expect(page.locator('.sx__calendar')).toBeVisible({ timeout: 15000 })
  const start = await currentTheme(page)
  const other: Theme = start === 'dark' ? 'light' : 'dark'

  // Week view, so a remount (back to month-grid) can't pass.
  await page.locator('.sx__view-selection-selected-item').click()
  await page.locator('.sx__view-selection-items button', { hasText: 'Week' }).click()
  const before = await snapshot(page)
  expect(before.view).toContain('Week')
  await expectThemed(page, before)

  await flipTheme(page, other)
  const flipped = await snapshot(page)
  expect(flipped.chrome).not.toBe(before.chrome)
  expect(flipped.event).not.toBe(before.event)
  expect(flipped.view).toBe(before.view)
  expect(flipped.range).toBe(before.range)
  await expectThemed(page, flipped)
  await expectPopupThemed(page)

  // A week on and back keeps the event in sight; the stop in between proves a
  // non-default date survives the switch too.
  const forward = page.locator('.sx__forward-backward-navigation .sx__chevron-wrapper').last()
  await forward.click()
  await expect(page.locator('.sx__range-heading')).not.toHaveText(flipped.range)
  const awayRange = ((await page.locator('.sx__range-heading').textContent()) ?? '').trim()
  await flipTheme(page, start)
  await expect(page.locator('.sx__range-heading')).toHaveText(awayRange)
  await expect(page.locator('.sx__view-selection-selected-item')).toHaveText(before.view)
  await page.locator('.sx__forward-backward-navigation .sx__chevron-wrapper').first().click()

  const back = await snapshot(page)
  expect(back).toEqual(before)
  await expectThemed(page, back)
  await expectPopupThemed(page)
})

test('every event colour pair reads at 4.5:1 or better in both themes', async ({ page }) => {
  await page.goto('/calendar')
  await expect(page.locator('.sx__calendar')).toBeVisible({ timeout: 15000 })
  const start = await currentTheme(page)
  for (const theme of [start, start === 'dark' ? 'light' : 'dark', start] as Theme[]) {
    if ((await currentTheme(page)) !== theme) await flipTheme(page, theme)
    for (const type of CAL_TYPES) {
      const ratio = await contrast(
        page,
        await computed(page, `var(--color-cal-${type}-on)`),
        await computed(page, `var(--color-cal-${type}-container)`),
      )
      expect(ratio, `${theme} ${type} on/container is ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5)
    }
  }
})

/** One screen pixel's RGB, out of a 1x1 screenshot (filter byte, then r, g, b). */
async function pixel(page: Page, x: number, y: number): Promise<number[]> {
  const png = await page.screenshot({ clip: { x: Math.round(x), y: Math.round(y), width: 1, height: 1 } })
  // The image data can come in more than one IDAT chunk.
  const data: Buffer[] = []
  for (let at = 8; at < png.length; ) {
    const length = png.readUInt32BE(at)
    if (png.toString('latin1', at + 4, at + 8) === 'IDAT') data.push(png.subarray(at + 8, at + 8 + length))
    at += 12 + length
  }
  return [...inflateSync(Buffer.concat(data)).subarray(1, 4)]
}

/** Largest per-channel gap. Composited layers can round a blend by a unit or two. */
const gap = (a: number[], b: number[]): number => Math.max(...a.map((v, i) => Math.abs(v - b[i])))

test('the notes drawer dims the calendar, sticky week header included', async ({ page }) => {
  // Schedule-X gives its sticky week header z-index 100, which painted over the
  // drawer's backdrop (55). #root is inert under a drawer, so hit testing can't
  // see paint order; compare pixels instead. Both points are plain surface.
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/calendar')
  await expect(page.locator('.sx__calendar')).toBeVisible({ timeout: 15000 })
  await page.locator('.sx__view-selection-selected-item').click()
  await page.locator('.sx__view-selection-items button', { hasText: 'Week' }).click()
  const header = page.locator('.sx__week-header')
  const day = page.locator('.sx__time-grid-day').last()
  await header.scrollIntoViewIfNeeded()
  const hb = (await header.boundingBox())!
  const db = (await day.boundingBox())!
  const headerPoint = [hb.x + 10, hb.y + 10] as const
  const gridPoint = [db.x + db.width / 2, db.y + 20] as const
  const plain = await pixel(page, ...headerPoint)
  expect(gap(await pixel(page, ...gridPoint), plain), 'pick two plain surface points').toBeLessThanOrEqual(2)

  // A DOM click, so Playwright doesn't scroll the button into view and move the points.
  await page.getByRole('button', { name: 'View notes' }).first().evaluate((el: HTMLElement) => el.click())
  await expect(page.getByTestId('drawer')).toContainText(NOTES)
  // Wait out the backdrop's fade, so the pixels are the settled ones.
  await expect.poll(() => page.getByTestId('drawer-backdrop').evaluate((el) => getComputedStyle(el).opacity)).toBe('1')
  expect((await header.boundingBox())!.y).toBe(hb.y)
  const dimmed = await pixel(page, ...gridPoint)
  const headerNow = await pixel(page, ...headerPoint)
  expect(gap(dimmed, plain), `the backdrop dims the grid (${plain} to ${dimmed})`).toBeGreaterThan(4)
  expect(gap(headerNow, dimmed), `the week header sits under the backdrop too (${headerNow} vs grid ${dimmed})`).toBeLessThanOrEqual(2)
})

test('Shift+Tab straight after opening the notes drawer stays inside it', async ({ page }) => {
  // Nothing to focus in the notes body, so focus parks on the panel. Shift+Tab
  // from there used to fall out of the drawer.
  await page.goto('/calendar')
  await expect(page.locator('.sx__calendar')).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: 'View notes' }).first().click()
  const drawer = page.getByTestId('drawer')
  await expect(drawer).toContainText(NOTES)
  await expect(drawer).toBeFocused()
  const inside = (): Promise<boolean> => drawer.evaluate((el) => el.contains(document.activeElement))
  await page.keyboard.press('Shift+Tab')
  expect(await inside(), 'Shift+Tab off the panel left the drawer').toBe(true)
  await expect(drawer).not.toBeFocused()
  await page.keyboard.press('Tab')
  expect(await inside(), 'Tab left the drawer').toBe(true)
})
