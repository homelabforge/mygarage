/**
 * Capture Ask My Garage PR screenshots into docs/screenshots/pr/ask-my-garage/.
 *
 * Prerequisites: backend on :8686, frontend on :3000, a vehicle with Overview
 * visible (default TRUCK VIN below matches local demo seed).
 *
 * Usage:
 *   PW_CHROME=/path/to/chrome-headless-shell bun scripts/capture_ask_my_garage_screenshots.mjs
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.resolve(__dirname, '../docs/screenshots/pr/ask-my-garage')
const BASE = process.env.MG_BASE || 'http://127.0.0.1:3000'
const TRUCK = process.env.MG_VIN || '1HGCM82633A004352'
const exe =
  process.env.PW_CHROME ||
  '/Users/michaelshaffer/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell'

async function dismissError(page) {
  const tryAgain = page.getByRole('button', { name: /Try Again/i })
  if (await tryAgain.count()) await tryAgain.click().catch(() => {})
}

async function scrollToHeading(page, pattern) {
  await page.evaluate((reSource) => {
    const re = new RegExp(reSource, 'i')
    const el = [...document.querySelectorAll('h2,h3')].find((h) => re.test(h.textContent || ''))
    el?.scrollIntoView({ block: 'center' })
  }, pattern.source)
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true })
  const browser = await chromium.launch({ headless: true, executablePath: exe })
  const page = await browser.newPage({ viewport: { width: 1280, height: 1100 } })
  page.on('pageerror', (e) => console.log('PAGEERROR', e.message))

  await page.goto(`${BASE}/vehicles/${TRUCK}`, { waitUntil: 'networkidle' })
  await dismissError(page)
  await page.waitForTimeout(1200)

  // ---- Fluids & torque card ----
  await page.getByText(/Fluids & torque|Fluids and torque/i).first().waitFor({ timeout: 20000 })
  await scrollToHeading(page, /fluids/i)
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(OUT, 'fluids-torque-card.png') })
  console.log('wrote fluids-torque-card.png')

  // ---- Specs editor drawer ----
  await page.getByRole('button', { name: /Edit fluids and torque specs/i }).click()
  await page.getByRole('dialog').waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(OUT, 'fluids-torque-editor.png') })
  console.log('wrote fluids-torque-editor.png')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)

  // ---- Ask My Garage panel (disabled or enabled) ----
  await page.getByText(/Ask My Garage/i).first().waitFor({ timeout: 15000 })
  await scrollToHeading(page, /ask my garage/i)
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(OUT, 'ask-my-garage-panel.png') })
  console.log('wrote ask-my-garage-panel.png')

  // ---- Settings → Integrations LLM section ----
  await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' })
  await dismissError(page)
  await page.waitForTimeout(800)
  const integrationsTab = page.getByRole('tab', { name: /Integrations/i })
  if (await integrationsTab.count()) {
    await integrationsTab.click()
    await page.waitForTimeout(600)
  }
  await page.getByText(/LLM features|Ask My Garage|receipt/i).first().waitFor({ timeout: 15000 })
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('h2,h3')].find((h) =>
      /llm|ask my garage|receipt/i.test(h.textContent || ''),
    )
    el?.scrollIntoView({ block: 'center' })
  })
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(OUT, 'settings-llm.png') })
  console.log('wrote settings-llm.png')

  await browser.close()
  console.log(`done → ${OUT}`)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
