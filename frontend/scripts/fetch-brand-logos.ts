/**
 * Fetch the brand logos the make picker shows (#219 takeover).
 *
 * Run by hand when the catalog's logo list changes, never in CI or the build:
 *
 *   cd frontend && bun run scripts/fetch-brand-logos.ts
 *
 * Reads every `logo` slug in src/constants/carCatalog.json, downloads that
 * thumbnail from filippofilip95/car-logos-dataset at a pinned commit, and
 * writes public/brand-logos/<slug>.png plus NOTICE.md. The files are
 * committed, so the app never fetches anything at runtime.
 */

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const DATASET = 'filippofilip95/car-logos-dataset'
/** Pinned so a re-run fetches the same images (2026-10-23). */
const COMMIT = 'e334a4d2e8742108ba164c629dff5636576d3808'
const MAX_BYTES = 64 * 1024
const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const catalogPath = join(root, 'src', 'constants', 'carCatalog.json')
const outDir = join(root, 'public', 'brand-logos')

interface CatalogMake {
  name: string
  logo?: string
}

function isPng(bytes: Uint8Array): boolean {
  return PNG_SIGNATURE.every((byte, i) => bytes[i] === byte)
}

async function main(): Promise<void> {
  const catalog = JSON.parse(readFileSync(catalogPath, 'utf-8')) as CatalogMake[]
  const slugs = [...new Set(catalog.map((m) => m.logo).filter((s): s is string => !!s))].sort()
  for (const slug of slugs) {
    if (!SLUG.test(slug)) throw new Error(`refusing slug ${JSON.stringify(slug)}`)
  }
  mkdirSync(outDir, { recursive: true })

  for (const slug of slugs) {
    const url = `https://raw.githubusercontent.com/${DATASET}/${COMMIT}/logos/thumb/${slug}.png`
    const response = await fetch(url)
    if (!response.ok) throw new Error(`${slug}: HTTP ${response.status}`)
    const bytes = new Uint8Array(await response.arrayBuffer())
    if (bytes.length > MAX_BYTES) throw new Error(`${slug}: ${bytes.length} bytes, over ${MAX_BYTES}`)
    if (!isPng(bytes)) throw new Error(`${slug}: not a PNG`)
    writeFileSync(join(outDir, `${slug}.png`), bytes)
  }

  writeFileSync(
    join(outDir, 'NOTICE.md'),
    [
      '# Brand logos',
      '',
      `The ${slugs.length} thumbnails in this folder come from`,
      `[${DATASET}](https://github.com/${DATASET}) at commit \`${COMMIT}\`,`,
      'MIT licensed. That dataset crawled them from carlogos.org.',
      '',
      'The logos are trademarks of their respective owners and are shown only to',
      'identify each make. A maker that wants its logo removed: delete its PNG and',
      'the `logo` field of its entry in `src/constants/carCatalog.json`.',
      '',
      'Regenerate with `bun run scripts/fetch-brand-logos.ts` from `frontend/`.',
      '',
    ].join('\n'),
  )
  console.log(`✓ ${slugs.length} logos written to public/brand-logos/`)
}

await main()
