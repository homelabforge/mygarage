import { existsSync, readFileSync, writeFileSync } from 'node:fs'

/**
 * sw.js lives in public/ and is copied verbatim to dist/ during Vite's
 * prepare-outDir step, so it cannot import the Rollup asset manifest — the
 * hashed .woff2 filenames only exist once the bundle is built. The
 * `mygarage-sw-font-assets` Vite plugin (vite.config.ts) calls this after
 * the build to rewrite the `FONT_ASSETS_MARKER` placeholder in dist/sw.js
 * into the real font list, so the service worker can precache them.
 *
 * Factored out of the plugin so the substitution — and specifically its
 * failure-mode guarantees — is unit-testable without needing a real `vite
 * build` to have already produced a dist/ directory (see
 * src/__tests__/sw-font-assets.test.ts). The plugin itself then enforces
 * the same guarantees on every real build: any of the throws below fails
 * `vite build` outright, so a broken substitution can never ship silently.
 * That is deliberate — this file previously returned/no-opped on every one
 * of these paths instead of failing, which is exactly how font precaching
 * could silently stop working (Task 9 built it, Task 12 B3 closed this gap).
 */
export const FONT_ASSETS_MARKER = '/*__FONT_ASSETS__*/[]'
export const MIN_FONT_ASSET_COUNT = 12

export class SwFontInjectionError extends Error {}

/** Rollup's `bundle` map keys include every emitted asset; keep only fonts. */
export function buildFontAssetsList(bundleFileNames: readonly string[]): string[] {
  return bundleFileNames.filter((f) => f.endsWith('.woff2')).map((f) => `./${f}`)
}

/**
 * Pure substitution + validation, operating on already-loaded source text so
 * it can be exercised directly against a fixture in tests. Throws instead of
 * returning the untouched source on any failure:
 *   - the marker isn't found (nothing to replace — the exact silent no-op
 *     the original writeBundle hook had via `if (replaced !== source)`),
 *   - the marker is somehow still present after substitution (a malformed
 *     replacement), or
 *   - too few font assets were found to plausibly be the real font set
 *     (Inter Variable + JetBrains Mono Variable currently emit well over
 *     MIN_FONT_ASSET_COUNT .woff2 subsets between them).
 */
export function injectFontAssetsIntoSource(source: string, fonts: readonly string[]): string {
  const replaced = source.replace(FONT_ASSETS_MARKER, JSON.stringify(fonts))

  if (replaced === source) {
    throw new SwFontInjectionError(
      `FONT_ASSETS marker (${FONT_ASSETS_MARKER}) not found in sw.js source — font ` +
        'precache injection would silently no-op and ship an empty precache list.',
    )
  }
  if (replaced.includes(FONT_ASSETS_MARKER)) {
    throw new SwFontInjectionError(
      'Residual FONT_ASSETS marker still present in sw.js after substitution.',
    )
  }
  if (fonts.length < MIN_FONT_ASSET_COUNT) {
    throw new SwFontInjectionError(
      `Only ${fonts.length} .woff2 asset(s) found for the sw.js font precache — expected ` +
        `at least ${MIN_FONT_ASSET_COUNT}. Either the font packages regressed or the bundle ` +
        'filter stopped matching real font output.',
    )
  }

  return replaced
}

/** Real filesystem entry point — reads swPath, injects, writes it back. */
export function injectSwFontAssets(swPath: string, bundleFileNames: readonly string[]): void {
  if (!existsSync(swPath)) {
    throw new SwFontInjectionError(`${swPath} does not exist — cannot inject font assets into it.`)
  }
  const source = readFileSync(swPath, 'utf-8')
  const fonts = buildFontAssetsList(bundleFileNames)
  const replaced = injectFontAssetsIntoSource(source, fonts)
  writeFileSync(swPath, replaced)
}
