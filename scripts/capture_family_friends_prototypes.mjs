/**
 * Capture Family & Friends / Customers HTML prototypes into
 * docs/screenshots/pr/family-friends/.
 *
 * Usage: node scripts/capture_family_friends_prototypes.mjs
 * Serves the prototype directory on a local port; no app backend required.
 */
import { chromium } from 'playwright'
import { createServer } from 'http'
import { readFile } from 'fs/promises'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const PROTO = path.join(ROOT, 'docs/prototypes/family-friends')
const OUT = path.join(ROOT, 'docs/screenshots/pr/family-friends')
const exe =
  process.env.PW_CHROME ||
  path.join(
    ROOT,
    '.pw-browsers/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell',
  )

const PAGES = [
  ['index-flat.html', 'flat-sections.png'],
  ['index-empty.html', 'empty-state.png'],
  ['index-grouped.html', 'grouped-by-person.png'],
  ['index-reference.html', 'reference-mix.png'],
  ['index-customers.html', 'customers-section.png'],
]

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
}

function startServer() {
  return new Promise((resolve) => {
    const server = createServer(async (req, res) => {
      try {
        const urlPath = decodeURIComponent((req.url || '/').split('?')[0])
        const rel = urlPath === '/' ? '/index-flat.html' : urlPath
        const filePath = path.join(PROTO, rel)
        if (!filePath.startsWith(PROTO)) {
          res.writeHead(403)
          res.end('Forbidden')
          return
        }
        const data = await readFile(filePath)
        const ext = path.extname(filePath)
        res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' })
        res.end(data)
      } catch {
        res.writeHead(404)
        res.end('Not found')
      }
    })
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address()
      resolve({ server, port })
    })
  })
}

async function main() {
  const { mkdir } = await import('fs/promises')
  await mkdir(OUT, { recursive: true })

  const { server, port } = await startServer()
  const base = `http://127.0.0.1:${port}`
  console.log('serving prototypes at', base)

  const browser = await chromium.launch({ headless: true, executablePath: exe })
  const page = await browser.newPage({ viewport: { width: 1280, height: 1100 } })

  for (const [html, png] of PAGES) {
    await page.goto(`${base}/${html}`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(300)
    const outPath = path.join(OUT, png)
    await page.screenshot({ path: outPath, fullPage: true })
    console.log('wrote', png)
  }

  await browser.close()
  server.close()
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
