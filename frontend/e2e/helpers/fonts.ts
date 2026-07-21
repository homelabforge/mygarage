import type { Page } from '@playwright/test'

/**
 * Resolves whether a font family actually loads — NOT via
 * `document.fonts.check()` alone. That method has two failure modes here:
 * it reflects only whether a font happens to already be in use on the
 * current DOM (Dashboard renders no monospace text, so JetBrains Mono stays
 * 'unloaded' regardless of whether the asset works), AND — verified by
 * temporarily deleting the font import while writing this test — it
 * returns `true` when ZERO `@font-face` rules match the family at all,
 * because there is trivially nothing "pending". So this filters
 * `document.fonts` down to faces that actually declare the family, fails
 * outright if that set is empty, then calls `.load()` on each match and
 * requires every one to reach `status === 'loaded'`.
 *
 * Loads are sequential (a `for` loop), NOT `Promise.all` — cheaper and
 * deterministic to reason about, and avoids depending on unspecified
 * browser-internal scheduling when many faces load at once.
 *
 * One more wrinkle, found while adding the subpath (production-build)
 * variant of this test: Vite inlines any bundled asset under its
 * `assetsInlineLimit` (default 4KB) as a base64 `data:` URI directly in the
 * built CSS instead of emitting a separate hashed file — true here for the
 * smallest font subset (JetBrains Mono's `cyrillic-ext`, ~2KB). Chromium's
 * `FontFace.load()` throws a bare "NetworkError" for a `data:`-sourced face
 * even though the bytes are embedded right there in the already-loaded CSS
 * and render fine through normal (non-JS-API) usage — confirmed by cloning
 * a fresh `FontFace` with the identical `data:` src and watching it fail
 * identically, and by the dev server (which never inlines: `vite dev` skips
 * asset processing entirely) never reproducing it. This is orthogonal to
 * what this test exists to catch: a `data:` URI has no URL to resolve under
 * a prefix, so it cannot be broken by the #107 subpath regression class by
 * construction — unlike a real emitted file, which is exactly what a broken
 * deploy (e.g. a font moved to public/) would still hit. So a `.load()`
 * failure is only excused when the face's own declared `src` is confirmed
 * (via the live CSSOM, not assumed) to be a `data:` URI; a real URL that
 * fails to load still fails this function, same as before.
 */
export async function familyLoads(page: Page, family: string): Promise<boolean> {
  return page.evaluate(async (fam) => {
    // Best-effort: finds the src url() declared for a face by matching the
    // live @font-face CSSOM on family + weight + style + unicode-range (the
    // most specific identifying tuple FontFace exposes). A rule that omits
    // one of these properties falls back to the CSS spec default rather than
    // the CSSOM's empty-string getPropertyValue() — otherwise a rule that,
    // say, never declares unicode-range (implicitly "all codepoints") would
    // never match its FontFace's normalized 'U+0-10FFFF' and this would
    // wrongly report "no matching rule" for a perfectly ordinary face.
    const DEFAULTS: Record<string, string> = {
      'unicode-range': 'U+0-10FFFF',
      'font-weight': 'normal',
      'font-style': 'normal',
    }
    function declaredSrcUrl(face: FontFace): string | null {
      for (const sheet of document.styleSheets) {
        let rules: CSSRuleList
        try {
          rules = sheet.cssRules
        } catch {
          continue // cross-origin stylesheet; not one of ours
        }
        for (const rule of rules) {
          if (!(rule instanceof CSSFontFaceRule)) continue
          const style = rule.style
          const prop = (name: string) => style.getPropertyValue(name) || DEFAULTS[name]
          const ruleFamily = style.getPropertyValue('font-family').replace(/^["']|["']$/g, '')
          if (
            ruleFamily !== face.family ||
            prop('unicode-range') !== face.unicodeRange ||
            prop('font-weight') !== face.weight ||
            prop('font-style') !== face.style
          ) {
            continue
          }
          const match = style.getPropertyValue('src').match(/url\(["']?([^"')]+)["']?\)/)
          if (match) return match[1]
        }
      }
      return null
    }

    const matches = [...document.fonts].filter(
      (f) => f.family.replace(/^["']|["']$/g, '') === fam,
    )
    if (matches.length === 0) return false
    for (const f of matches) {
      try {
        await f.load()
      } catch {
        if (!declaredSrcUrl(f)?.startsWith('data:')) return false
        continue // data: URI — see the doc comment above.
      }
      if (f.status !== 'loaded') return false
    }
    return true
  }, family)
}

/** Result of {@link trackWoff2Requests}: every `.woff2` URL observed, and the subset that came back wrong. */
export interface Woff2Tracking {
  seen: string[]
  bad: string[]
}

/**
 * Attaches a `response` listener that records every `.woff2` request and
 * flags any that didn't come back as a real font.
 *
 * NOT a plain `!response.ok()` check. Verified while writing this: both the
 * Vite dev server (SPA history fallback) and the production backend's
 * custom_404_handler (backend/app/main.py) return 200 + text/html for ANY
 * unmatched path, including a broken /assets/*.woff2 reference — confirmed
 * by requesting a deliberately nonexistent .woff2 path and getting back 200
 * OK. So a status-only check can never observe this failure: the browser
 * would silently receive an HTML document, fail to parse it as a font, and
 * fall back to a system font — exactly the silent failure src/styles/fonts.css
 * exists to prevent. Checking content-type catches it instead.
 *
 * Must be called (and the returned `seen` array asserted non-empty) before
 * relying on `bad` being empty — see the two callers for why: without proof
 * that font traffic was observed at all, a build that stops requesting fonts
 * entirely would leave `bad` empty too, and a bare `expect(bad).toEqual([])`
 * would pass for the wrong reason.
 */
export function trackWoff2Requests(page: Page): Woff2Tracking {
  const tracking: Woff2Tracking = { seen: [], bad: [] }
  page.on('response', (r) => {
    if (!r.url().endsWith('.woff2')) return
    tracking.seen.push(r.url())
    const contentType = r.headers()['content-type'] ?? ''
    if (r.status() !== 200 || !contentType.startsWith('font/')) {
      tracking.bad.push(`${r.status()} ${contentType} ${r.url()}`)
    }
  })
  return tracking
}
