import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve, join } from 'node:path'
import * as ts from 'typescript'

const ROOT = resolve(__dirname, '../..')
const SRC = resolve(ROOT, 'src')

/**
 * Tailwind emits nothing for a color utility whose theme variable is undefined —
 * there is no error for a class that was never generated. That is how
 * `--color-primary` shipped undefined across ~589 call sites, and how the eight
 * `garage-*` names below are silently no-ops on main today.
 *
 * This test is the tripwire for that entire bug class.
 *
 * DESIGN PRINCIPLE — fail safe, not fail open. A candidate token is presumed to be
 * a real color reference and MUST resolve to a defined `--color-*` token UNLESS it
 * is provably something else:
 *   - one of Tailwind's built-in default-palette names (BUILTIN), or
 *   - a known non-color utility VALUE for that prefix (NON_COLOR_VALUES / the
 *     opacity-N and gradient-to-<dir> patterns) — e.g. `text-sm`, `border-2`,
 *     `bg-cover`.
 * A new, unrecognized color family is NOT grounds for exclusion — it falls through
 * to the defined-token check like everything else. Getting NON_COLOR_VALUES
 * slightly wrong produces a false positive (test fails, a human adds a keyword) —
 * a safe, self-correcting failure. The previous design used a positive whitelist of
 * known family names instead: anything outside it was silently dropped before the
 * defined/undefined comparison ever ran, so `bg-info`/`text-info`/`border-info`
 * (12 call sites, `--color-info` undefined) passed clean. That is fail-open, and is
 * exactly the failure mode this test exists to prevent.
 */
const COLOR_PREFIXES = [
  'bg', 'text', 'border', 'ring', 'from', 'to', 'via', 'fill', 'stroke', 'divide',
  'outline', 'decoration', 'accent', 'caret', 'shadow',
]

/** Palette names Tailwind ships by default — always defined, never our problem. */
const BUILTIN = new Set([
  'inherit', 'current', 'transparent', 'black', 'white',
  'slate', 'gray', 'zinc', 'neutral', 'stone', 'red', 'orange', 'amber',
  'yellow', 'lime', 'green', 'emerald', 'teal', 'cyan', 'sky', 'blue',
  'indigo', 'violet', 'purple', 'fuchsia', 'pink', 'rose',
])

/**
 * Directional/positional segments that precede a color name rather than being part
 * of it: `border-l-primary` / `divide-y-primary` (border & divide sides — top,
 * right, bottom, left, start, end, horizontal, vertical) and `ring-offset-*` /
 * `outline-offset-*`. The capture group is greedy across hyphens (it has to be, to
 * catch multi-segment names like `garage-surface-light`), so without stripping
 * these first, `border-l-primary` resolves as the color name `l-primary` — it
 * fails the "is this defined" check for the wrong reason and, if `primary` were
 * ever undefined, the blob `l-primary` would silently never match anything and the
 * gate would stay green. Bare directional utilities with no color after them
 * (`border-b`, `divide-y`) strip down to an empty string and are skipped — there is
 * no color reference to check.
 */
const POSITIONAL_SEGMENTS = new Set(['t', 'r', 'b', 'l', 's', 'e', 'x', 'y', 'offset'])

/**
 * Non-color utility VALUES that share a prefix with a color utility. This is a
 * deny-list of known Tailwind/CSS keywords, not a whitelist of known color
 * families — an unrecognized family still falls through to the defined-token
 * check. Sizes (`text-sm`), alignment (`text-center`), border styles
 * (`border-dashed`), and a couple of incidental collisions between a color prefix
 * and plain English inside a string literal (`text-anchor` in an inline SVG
 * attribute, `border-radius` in an inline style string) — real, but not colors.
 */
// This list is hand-maintained and expected to grow as the reskin introduces new
// utility keywords. A false positive here (a real Tailwind keyword not yet listed)
// is the intended safe direction — a loud CI failure a human resolves by adding the
// keyword, never a silent pass. Confirmed misses get added as they're found, e.g.
// `shadow-inner` (reported `inner`) and `text-start` (reported `start`).
const NON_COLOR_VALUES = new Set([
  'xs', 'sm', 'md', 'lg', 'xl', '2xl', '3xl',
  'base', 'center', 'left', 'right', 'none', 'hidden',
  'dashed', 'solid', 'double', 'collapse', 'separate', 'cover', 'contain',
  'radius', 'anchor',
  'inner', 'start', 'end', 'justify', 'dotted', 'wavy', 'auto', 'from-font',
])

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === '__tests__' || entry === 'node_modules') continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.tsx?$/.test(full)) out.push(full)
  }
  return out
}

/** Every `--color-<name>` declared in index.css. */
function collectDefinedColorTokens(): Set<string> {
  const css = readFileSync(resolve(SRC, 'index.css'), 'utf8')
  const defined = new Set<string>()
  for (const m of css.matchAll(/--color-([a-z0-9-]+)\s*:/g)) defined.add(m[1])
  return defined
}

/**
 * Every string-literal-shaped text span in a file, extracted from the parsed AST
 * rather than from raw text: whole string literals, no-substitution template
 * literals, and each literal segment (head/middle/tail) of a substitution template
 * literal — wherever in the file they appear syntactically.
 *
 * This replaces a `stripComments()` regex (`/\*[\s\S]*?\*\//g`) that matched
 * against raw source with no awareness of string boundaries. A bare `/*` inside a
 * string literal, paired by the regex with the next unrelated `*\/` anywhere later
 * in the file, silently deleted everything between them from the scan — live in
 * this codebase: `VehicleWizard.tsx` has `accept="image/*"` followed some lines
 * later by the JSX comment `{/* Step 4: Review *\/}`, hiding a real span of
 * `className` attributes from the gate. Comments are never part of this scan at
 * all — the parser treats them as trivia, not text — so that failure mode is
 * structurally impossible here, regardless of what any string literal contains.
 *
 * Deliberately not scoped to `className`/`class` JSX attributes only (the AST
 * would trivially support that narrower scope). Two real patterns in this
 * codebase put color-utility strings outside any JSX attribute entirely:
 *   - `CurrencyInputPrefix.tsx` / `TimeInput24.tsx` hoist a `DEFAULT_CLASS`
 *     constant and reference it (`className={className ?? DEFAULT_CLASS}`); the
 *     literal itself lives in a plain `const` initializer.
 *   - `schemas/auth.ts` returns `{ color: 'text-red-500' | ... }` from a plain
 *     function, consumed via `` className={`text-xs font-medium ${passwordStrength.color}`} ``
 *     in `Register.tsx` — a cross-file, non-JSX flow a `className`-attribute-only
 *     scope can't see without full data-flow analysis.
 * Scoping strictly to `className` attributes would silently stop scanning both,
 * trading the comment blind spot for an equally silent new one. Scanning every
 * literal instead has no such gap: no color-utility string, wherever it's
 * declared, can go unseen. Comments and JSX text (`JsxText` nodes, never string
 * literals) are excluded structurally either way. The remaining risk — a plain
 * string that happens to read like `prefix-word` but isn't a class reference
 * (`text-anchor` in an inline SVG data URI, `border-radius` in a Leaflet HTML
 * template literal) — is exactly what `NON_COLOR_VALUES` already exists to
 * absorb, and both of those are already-documented entries there.
 */
function collectLiteralTexts(file: string): string[] {
  const sourceText = readFileSync(file, 'utf8')
  const scriptKind = file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  const sourceFile = ts.createSourceFile(file, sourceText, ts.ScriptTarget.Latest, false, scriptKind)

  const texts: string[] = []
  const visit = (node: ts.Node): void => {
    switch (node.kind) {
      case ts.SyntaxKind.StringLiteral:
      case ts.SyntaxKind.NoSubstitutionTemplateLiteral:
      case ts.SyntaxKind.TemplateHead:
      case ts.SyntaxKind.TemplateMiddle:
      case ts.SyntaxKind.TemplateTail:
        texts.push((node as ts.LiteralLikeNode).text)
        break
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  return texts
}

/** Strip a leading directional/positional segment; '' if nothing colored follows. */
function stripPositionalSegment(token: string): string {
  const segments = token.split('-')
  if (POSITIONAL_SEGMENTS.has(segments[0])) return segments.slice(1).join('-')
  return token
}

/** Every custom color token referenced by a utility class in source. */
function collectUsedColorTokens(): Map<string, string[]> {
  const used = new Map<string, string[]>()
  const pattern = new RegExp(
    String.raw`(?<![a-z0-9-])(?:${COLOR_PREFIXES.join('|')})-([a-z][a-z0-9]*(?:-[a-z0-9]+)*)(?![a-z0-9-])`,
    'g',
  )
  for (const file of walk(SRC)) {
    const rel = file.slice(ROOT.length + 1)
    for (const text of collectLiteralTexts(file)) {
      for (const m of text.matchAll(pattern)) {
        const token = stripPositionalSegment(m[1])
        if (!token || !/^[a-z]/.test(token)) continue // bare directional utility, no color

        // Provably not a color reference — everything else falls through to the
        // defined-token check below, whatever family it claims to be.
        const head = token.split('-')[0]
        if (BUILTIN.has(head)) continue
        if (NON_COLOR_VALUES.has(token)) continue
        if (/^opacity-\d+$/.test(token)) continue
        if (/^gradient-to-(t|tr|r|br|b|bl|l|tl)$/.test(token)) continue

        used.set(token, [...(used.get(token) ?? []), rel])
      }
    }
  }
  return used
}

describe('design tokens', () => {
  it('every custom color utility in source resolves to a defined token', () => {
    const defined = collectDefinedColorTokens()
    const used = collectUsedColorTokens()

    const undefinedTokens = [...used.entries()]
      .filter(([token]) => !defined.has(token))
      .map(([token, files]) => `${token}  ← ${[...new Set(files)].join(', ')}`)

    expect(undefinedTokens,
      'These utilities emit no CSS at all. Either define the token in ' +
      'src/index.css @theme, or fix the class name.\n\n' +
      undefinedTokens.join('\n'),
    ).toEqual([])
  })

  const SEMANTIC = [
    'bg', 'nav', 'surface', 'surface-2', 'surface-3',
    'border', 'border-soft', 'hair',
    'text', 'text-dim', 'text-mid', 'text-mute', 'text-faint',
  ]

  it.each(SEMANTIC)('defines the semantic token --color-%s', (token) => {
    expect(collectDefinedColorTokens()).toContain(token)
  })

  const LEGACY_ALIASES = [
    'garage-bg', 'garage-surface', 'garage-surface-light',
    'garage-border', 'garage-text', 'garage-text-muted',
    'garage-primary', 'garage-primary-dark',
  ]

  it.each(LEGACY_ALIASES)('keeps the legacy alias --color-%s alive', (token) => {
    expect(collectDefinedColorTokens()).toContain(token)
  })

  it('re-points legacy aliases at semantic tokens rather than duplicating hex', () => {
    const css = readFileSync(resolve(SRC, 'index.css'), 'utf8')
    // Each alias must be defined as a var() reference, not a literal colour.
    for (const alias of ['garage-bg', 'garage-surface', 'garage-border', 'garage-text']) {
      const decl = new RegExp(String.raw`--color-${alias}\s*:\s*var\(`)
      expect(css, `--color-${alias} must alias a semantic token`).toMatch(decl)
    }
  })

  it('uses plain @theme, never @theme inline', () => {
    const css = readFileSync(resolve(SRC, 'index.css'), 'utf8')
    expect(css).not.toMatch(/@theme\s+inline/)
  })

  it('uses the Tailwind v4 font token names', () => {
    const css = readFileSync(resolve(SRC, 'index.css'), 'utf8')
    expect(css).toMatch(/--font-sans\s*:/)
    expect(css).toMatch(/--font-mono\s*:/)
    expect(css).not.toMatch(/--font-family-(sans|mono)\s*:/)
  })

  /**
   * The AST scanner only walks .ts/.tsx, so the nine `@apply` lines in index.css
   * itself — which back the .btn/.input/.card/.badge primitives — are invisible
   * to it. That gap is harmless while token names are stable, but THIS task
   * rewrites the whole @theme block and Task 4 rewrites those very @apply rules,
   * which is precisely when a renamed token would slip through unprotected.
   */
  it('every color token used by an @apply rule in index.css is defined', () => {
    const css = readFileSync(resolve(SRC, 'index.css'), 'utf8')
    const defined = collectDefinedColorTokens()
    const bad: string[] = []

    for (const m of css.matchAll(/@apply\s+([^;]+);/g)) {
      for (const cls of m[1].split(/\s+/).filter(Boolean)) {
        // Drop any variant prefixes (hover:, focus:, html.light &, etc.)
        const bare = cls.split(':').pop() as string
        const hit = bare.match(
          /^(?:bg|text|border|ring|from|to|via|fill|stroke|divide|outline|decoration|caret|shadow|placeholder)-(.+)$/,
        )
        if (!hit) continue
        // Strip a Tailwind opacity modifier (`bg-black/50`, `bg-success-600/20`) —
        // unlike collectUsedColorTokens's character-class match, this naive
        // whitespace split keeps the slash, so `black/50` never matched the
        // `black` BUILTIN and `success-600/20` never matched the defined
        // `success-600` token. Same colour, same rule, just written differently.
        const token = hit[1].replace(/\/\d+$/, '')
        // Bare digits after a prefix are a width, not a colour: `ring-2`,
        // `border-4`. Mirrors the `opacity-\d+` carve-out in
        // collectUsedColorTokens below.
        if (/^\d+$/.test(token)) continue
        if (BUILTIN.has(token.split('-')[0])) continue
        if (NON_COLOR_VALUES.has(token)) continue
        if (!defined.has(token)) bad.push(`${cls} → --color-${token}`)
      }
    }

    expect(bad,
      'index.css @apply references a colour token that @theme never defines. ' +
      'Tailwind emits nothing for these.\n\n' + bad.join('\n'),
    ).toEqual([])
  })
})
