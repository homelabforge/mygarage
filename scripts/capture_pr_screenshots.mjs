/**
 * Capture PR screenshots for tires + EV charge session UI.
 */
import { chromium } from 'playwright'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.resolve(__dirname, '../docs/screenshots/pr')
const BASE = 'http://127.0.0.1:3000'
const CIVIC = '1HGCM82633A004352'
const TESLA = '5YJSA1E26MF123456'
const exe =
  process.env.PW_CHROME ||
  '/Users/michaelshaffer/Projects/mygarage/.pw-browsers/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell'

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: exe })
  const page = await browser.newPage({ viewport: { width: 1280, height: 1100 } })

  // ---- Tires tab (Civic) ----
  await page.goto(`${BASE}/vehicles/${CIVIC}`, { waitUntil: 'networkidle' })
  await page.getByRole('tab', { name: /^Maintenance$/i }).click()
  await page.waitForTimeout(400)
  await page.getByRole('tab', { name: /^Tires$/i }).click()
  await page.waitForSelector('text=Michelin', { timeout: 10000 })
  // Scroll content into view so all four tire cards show
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('h2')].find((h) =>
      /tires/i.test(h.textContent || '')
    )
    el?.scrollIntoView({ block: 'start' })
  })
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(OUT, 'tires-tab.png') })
  console.log('wrote tires-tab.png')

  // ---- EV fuel history + charge form (Tesla) ----
  await page.goto(`${BASE}/vehicles/${TESLA}`, { waitUntil: 'networkidle' })
  await page.getByRole('tab', { name: /^Fuel$/i }).click()
  await page.waitForTimeout(800)
  // Close any stray drawer
  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(OUT, 'ev-fuel-history.png') })
  console.log('wrote ev-fuel-history.png')

  // Open charge form from Fuel History ("Add Fill-up"), not the hero "Add Fuel" tab switcher
  await page.getByRole('button', { name: /^Add Fill-up$/i }).click()
  await page.locator('#kwh').waitFor({ timeout: 10000 })
  // Prefill EV charge-session fields so the screenshot shows the new UI
  await page.locator('#kwh').fill('42.5')
  const socStart = page.locator('#soc_start_pct')
  if (await socStart.count()) {
    await socStart.fill('18')
    await page.locator('#soc_end_pct').fill('80')
    await page.locator('#battery_soh_pct').fill('94')
    await page.locator('#charge_level').selectOption('L2')
    await page.locator('#charge_location').selectOption('home')
  }
  await page.evaluate(() => {
    document.querySelector('#soc_start_pct')?.scrollIntoView({ block: 'center' })
  })
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(OUT, 'ev-charge-session.png'), fullPage: false })
  console.log('wrote ev-charge-session.png')

  await browser.close()
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
