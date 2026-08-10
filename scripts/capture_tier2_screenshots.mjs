/**
 * Capture Tier 2 PR screenshots into docs/screenshots/pr/tier2/.
 *
 * Prerequisites: backend on :8686, frontend on :3000, seeded demo vehicles.
 */
import { chromium } from 'playwright'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.resolve(__dirname, '../docs/screenshots/pr/tier2')
const BASE = 'http://127.0.0.1:3000'
const TRUCK = '1HGBH41JXMN109186'
const TRAILER = '1HGCM82633A004999'
const exe =
  process.env.PW_CHROME ||
  '/Users/michaelshaffer/Projects/mygarage/.pw-browsers/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell'

async function dismissError(page) {
  const tryAgain = page.getByRole('button', { name: /Try Again/i })
  if (await tryAgain.count()) await tryAgain.click().catch(() => {})
}

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: exe })
  const page = await browser.newPage({ viewport: { width: 1280, height: 1100 } })
  page.on('pageerror', (e) => console.log('PAGEERROR', e.message))

  // ---- Tow pairing on trailer Overview ----
  await page.goto(`${BASE}/vehicles/${TRAILER}`, { waitUntil: 'networkidle' })
  await dismissError(page)
  await page.waitForTimeout(1000)
  await page.getByText(/Trailer & tow vehicle|Tow pairing|Tow vehicle/i).first().waitFor({ timeout: 15000 })
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('h2,h3')].find((h) =>
      /trailer|tow/i.test(h.textContent || '')
    )
    el?.scrollIntoView({ block: 'center' })
  })
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(OUT, 'tow-pairing-trailer.png') })
  console.log('wrote tow-pairing-trailer.png')

  // ---- Linked trailers on tow truck ----
  await page.goto(`${BASE}/vehicles/${TRUCK}`, { waitUntil: 'networkidle' })
  await dismissError(page)
  await page.waitForTimeout(1000)
  await page.getByText(/Linked trailers/i).first().waitFor({ timeout: 15000 })
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('h2,h3')].find((h) =>
      /linked trailer/i.test(h.textContent || '')
    )
    el?.scrollIntoView({ block: 'center' })
  })
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(OUT, 'tow-linked-trailers.png') })
  console.log('wrote tow-linked-trailers.png')

  // ---- Reminder packs (Tracking → Reminders) ----
  await page.goto(`${BASE}/vehicles/${TRUCK}?tab=reminders`, { waitUntil: 'networkidle' })
  await dismissError(page)
  await page.waitForTimeout(1200)
  await page.locator('#reminder-pack').waitFor({ state: 'attached', timeout: 15000 })
  await page.getByRole('button', { name: /Apply pack/i }).waitFor({ timeout: 10000 })
  await page.evaluate(() => {
    document.querySelector('#reminder-pack')?.scrollIntoView({ block: 'center' })
  })
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(OUT, 'reminder-packs.png') })
  console.log('wrote reminder-packs.png')

  // ---- Vehicle type picker (expanded select) ----
  await page.goto(`${BASE}/vehicles/${TRUCK}`, { waitUntil: 'networkidle' })
  await dismissError(page)
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: /^Edit$/i }).first().click()
  await page.waitForTimeout(900)
  const typeSelect = page.locator('#vehicle_type').first()
  await typeSelect.waitFor({ timeout: 10000 })
  await typeSelect.scrollIntoViewIfNeeded()
  await typeSelect.evaluate((el) => {
    el.size = Math.min(el.options.length, 14)
    el.style.height = 'auto'
  })
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(OUT, 'vehicle-types.png') })
  console.log('wrote vehicle-types.png')

  // ---- Matrix settings ----
  await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.locator('button').filter({ hasText: /^Notifications$/i }).first().click()
  await page.waitForTimeout(800)
  await page.locator('button').filter({ hasText: /^Matrix$/i }).first().click()
  await page.waitForTimeout(700)
  await page.locator('#matrix_homeserver').waitFor({ timeout: 10000 })
  await page.screenshot({ path: path.join(OUT, 'matrix-settings.png') })
  console.log('wrote matrix-settings.png')

  // ---- Quick Entry deep link ----
  await page.goto(`${BASE}/quick-entry?action=add-fuel&vin=${TRUCK}`, {
    waitUntil: 'networkidle',
  })
  await page.waitForTimeout(1200)
  await page.screenshot({ path: path.join(OUT, 'quick-entry-deep-link.png') })
  console.log('wrote quick-entry-deep-link.png')

  await browser.close()
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
