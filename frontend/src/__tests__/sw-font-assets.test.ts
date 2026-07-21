import { describe, it, expect, afterEach } from 'vitest'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import {
  buildFontAssetsList,
  injectFontAssetsIntoSource,
  injectSwFontAssets,
  SwFontInjectionError,
  FONT_ASSETS_MARKER,
  MIN_FONT_ASSET_COUNT,
} from '../../scripts/inject-sw-font-assets'

const ROOT = resolve(__dirname, '../..')
const REAL_SW_SOURCE = readFileSync(resolve(ROOT, 'public/sw.js'), 'utf-8')

// A plausible real font list: Fontsource ships one .woff2 per unicode-range
// subset per family (latin, latin-ext, cyrillic, cyrillic-ext, greek,
// greek-ext, vietnamese — 7 for Inter, 7 for JetBrains Mono today), so a
// real build clears MIN_FONT_ASSET_COUNT comfortably. This fixture only
// needs to clear the threshold, not match the exact count.
const FAKE_BUNDLE_FILES = [
  'assets/index-abc123.js',
  'assets/index-def456.css',
  ...Array.from({ length: 14 }, (_, i) => `assets/font-${i}-${'a'.repeat(8)}.woff2`),
]

/**
 * This whole file exists so the substitution's failure-mode guarantees are
 * exercised on every `bun run test:run`, independent of whether dist/ has
 * been built. It never reads dist/ — it operates on public/sw.js (always
 * present, source-controlled) and on temp-file fixtures, so it can never
 * silently skip the way a test reading a possibly-absent dist/ could.
 * The real build path (vite.config.ts's writeBundle hook) is covered
 * separately by actually breaking and rebuilding in Task 12's manual proof
 * (see task-12-report.md) — this file covers the reusable logic itself.
 */
describe('sw.js font asset injection', () => {
  it('the real public/sw.js still contains the marker exactly once', () => {
    // Guards against B3's failure mode at the source: if someone reformats
    // or relocates the marker in public/sw.js (the literal string `.replace`
    // in injectFontAssetsIntoSource depends on matching verbatim), this
    // fails here with a clear reason instead of only failing deep inside a
    // production build.
    const occurrences = REAL_SW_SOURCE.split(FONT_ASSETS_MARKER).length - 1
    expect(occurrences, `expected exactly one "${FONT_ASSETS_MARKER}" in public/sw.js`).toBe(1)
  })

  describe('buildFontAssetsList', () => {
    it('keeps only .woff2 entries and prefixes each with "./"', () => {
      const result = buildFontAssetsList(FAKE_BUNDLE_FILES)
      expect(result).toHaveLength(14)
      for (const entry of result) {
        expect(entry.startsWith('./')).toBe(true)
        expect(entry.endsWith('.woff2')).toBe(true)
      }
    })

    it('returns an empty list when nothing matches', () => {
      expect(buildFontAssetsList(['assets/index-abc123.js'])).toEqual([])
    })
  })

  describe('injectFontAssetsIntoSource', () => {
    it('substitutes the marker with the JSON-encoded font list', () => {
      const fonts = buildFontAssetsList(FAKE_BUNDLE_FILES)
      const result = injectFontAssetsIntoSource(REAL_SW_SOURCE, fonts)

      expect(result).not.toContain(FONT_ASSETS_MARKER)
      expect(result).toContain(JSON.stringify(fonts))
      for (const font of fonts) {
        expect(result).toContain(font)
      }
    })

    it('throws instead of silently no-opping when the marker is absent', () => {
      const sourceWithoutMarker = REAL_SW_SOURCE.replace(FONT_ASSETS_MARKER, '[]')
      const fonts = buildFontAssetsList(FAKE_BUNDLE_FILES)
      expect(() => injectFontAssetsIntoSource(sourceWithoutMarker, fonts)).toThrow(
        SwFontInjectionError,
      )
    })

    it('throws when the marker has been reformatted/relocated (B3 regression)', () => {
      // Simulates exactly the regression named in the brief: the marker
      // survives as text but no longer matches the literal string the
      // substitution depends on.
      const reformatted = REAL_SW_SOURCE.replace(
        FONT_ASSETS_MARKER,
        '/* __FONT_ASSETS__ */ []',
      )
      const fonts = buildFontAssetsList(FAKE_BUNDLE_FILES)
      expect(() => injectFontAssetsIntoSource(reformatted, fonts)).toThrow(SwFontInjectionError)
    })

    it('throws when fewer than MIN_FONT_ASSET_COUNT fonts are found', () => {
      const tooFew = buildFontAssetsList(FAKE_BUNDLE_FILES).slice(0, MIN_FONT_ASSET_COUNT - 1)
      expect(() => injectFontAssetsIntoSource(REAL_SW_SOURCE, tooFew)).toThrow(
        SwFontInjectionError,
      )
    })

    it('throws if the marker is somehow still present after substitution', () => {
      // A source where the "replacement" is a no-op string identical to the
      // marker itself — replaced === source's residual-marker branch.
      const pathological = `${FONT_ASSETS_MARKER}${FONT_ASSETS_MARKER}`
      expect(() =>
        injectFontAssetsIntoSource(pathological, buildFontAssetsList(FAKE_BUNDLE_FILES)),
      ).toThrow(/[Rr]esidual/)
    })
  })

  describe('injectSwFontAssets (filesystem entry point)', () => {
    const tmpDirs: string[] = []
    const makeTmpDir = (): string => {
      const dir = mkdtempSync(join(tmpdir(), 'mygarage-sw-font-test-'))
      tmpDirs.push(dir)
      return dir
    }

    afterEach(() => {
      while (tmpDirs.length) {
        rmSync(tmpDirs.pop() as string, { recursive: true, force: true })
      }
    })

    it('writes the substituted source back to disk', () => {
      const dir = makeTmpDir()
      const swPath = join(dir, 'sw.js')
      writeFileSync(swPath, REAL_SW_SOURCE)

      injectSwFontAssets(swPath, FAKE_BUNDLE_FILES)

      const written = readFileSync(swPath, 'utf-8')
      expect(written).not.toContain(FONT_ASSETS_MARKER)
      expect(written).toContain('.woff2')
    })

    it('throws instead of silently returning when sw.js is missing', () => {
      const dir = makeTmpDir()
      const missingPath = join(dir, 'sw.js')
      expect(() => injectSwFontAssets(missingPath, FAKE_BUNDLE_FILES)).toThrow(
        SwFontInjectionError,
      )
    })
  })
})
