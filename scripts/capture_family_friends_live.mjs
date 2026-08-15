/**
 * Capture live Family & Friends dashboard + Settings toggle.
 * Prerequisites: backend :8686, frontend :3000, family_friends_enabled, auth_mode=none.
 *
 *   cd frontend && node ../scripts/capture_family_friends_live.mjs
 *   # or from repo root with NODE_PATH:
 *   NODE_PATH=frontend/node_modules node scripts/capture_family_friends_live.mjs
 */
import { createRequire } from 'module'
import path from 'path'
import { fileURLToPath, pathToFileURL } from 'url'
import { mkdir } from 'fs/promises'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const require = createRequire(path.join(__dirname, '../frontend/package.json'))
const { chromium } = require('playwright')

const OUT = path.resolve(__dirname, '../docs/screenshots/pr/family-friends')
const BASE = 'http://127.0.0.1:3000'
const exe =
  process.env.PW_CHROME ||
  path.resolve(
    __dirname,
    '../.pw-browsers/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell',
  )

async function main() {
  await mkdir(OUT, { recursive: true })
  const browser = await chromium.launch({ headless: true, executablePath: exe })
  const page = await browser.newPage({ viewport: { width: 1280, height: 1400 } })
  page.on('pageerror', (e) => console.log('PAGEERROR', e.message))

  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)

  await page.getByRole('heading', { name: /My Vehicles/i }).first().waitFor({ timeout: 20000 })
  await page.waitForTimeout(500)

  await page.screenshot({
    path: path.join(OUT, 'live-dashboard-full.png'),
    fullPage: true,
  })
  console.log('wrote live-dashboard-full.png')

  const family = page.getByRole('heading', { name: /Family & Friends/i }).first()
  if (await family.count()) {
    await family.scrollIntoViewIfNeeded()
    await page.waitForTimeout(400)
    await page.screenshot({ path: path.join(OUT, 'live-family-friends.png') })
    console.log('wrote live-family-friends.png')
  } else {
    console.log('skip live-family-friends.png (section not visible)')
  }

  await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  const garageHeading = page.getByText('Garage sections', { exact: true }).first()
  await garageHeading.waitFor({ timeout: 20000 })
  await garageHeading.scrollIntoViewIfNeeded()
  await page.waitForTimeout(400)
  await page.screenshot({
    path: path.join(OUT, 'live-settings-garage-sections.png'),
  })
  console.log('wrote live-settings-garage-sections.png')

  await browser.close()
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
