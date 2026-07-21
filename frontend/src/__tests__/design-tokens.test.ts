import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
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
  'outline', 'decoration', 'accent', 'caret', 'shadow', 'placeholder',
]

/**
 * The `(?:prefix1|prefix2|...)` alternation built from COLOR_PREFIXES, shared
 * verbatim by every scanner that needs to recognize a color-utility prefix:
 * `collectUsedColorTokens` (AST scan of .ts/.tsx) below, and the `@apply`
 * checker further down (raw-CSS scan of index.css). Before this, the two
 * scanners each hand-wrote their own copy of this alternation, and the copies
 * had drifted: COLOR_PREFIXES omitted `placeholder` while the @apply
 * checker's inline regex had it, so `placeholder-*` classes in .tsx source
 * were invisible to collectUsedColorTokens even though the identical prefix
 * was already recognized a few hundred lines away. That is the exact bug
 * class this file exists to prevent, just inside itself instead of in
 * src/. One list, derived here, used everywhere a prefix set is needed.
 */
const COLOR_PREFIX_ALTERNATION = COLOR_PREFIXES.join('|')

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

/**
 * Every `--color-<name>` declared in index.css, comments stripped first via
 * the same `stripCssComments` helper `collectDefinedCustomProperties` below
 * already uses — so a token name only ever *mentioned* inside a CSS comment
 * (e.g. "same omission as --color-warning:" in the doc comment above
 * `--color-info` today) can never register as defined. Previously this
 * function regexed the raw file directly, its own copy of the same mistake
 * `collectDefinedCustomProperties` had already been fixed for: a token named
 * only in a comment counted as defined, so a class pointed at that
 * never-really-defined token passed clean.
 */
function collectDefinedColorTokens(): Set<string> {
  const css = stripCssComments(readFileSync(resolve(SRC, 'index.css'), 'utf8'))
  const defined = new Set<string>()
  for (const m of css.matchAll(/--color-([a-z0-9-]+)\s*:/g)) defined.add(m[1])
  return defined
}

/** Tokens defined in the --shadow-* namespace. shadow-* utilities resolve here,
 *  not against --color-*, even though 'shadow' is a COLOR_PREFIXES member. */
function collectDefinedShadowTokens(): Set<string> {
  const css = stripCssComments(readFileSync(resolve(SRC, 'index.css'), 'utf8'))
  const defined = new Set<string>()
  for (const m of css.matchAll(/--shadow-([a-z0-9-]+)\s*:/g)) defined.add(m[1])
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

/**
 * True when a (prefix, token) pair is provably not a color reference and must
 * be exempted from the defined-token check — every `continue` branch inside
 * collectUsedColorTokens's loop below, factored out into one pure function so
 * the carve-out logic can be driven directly by synthetic inputs in a test
 * instead of only indirectly via "the rest of the suite still passes." That
 * indirection is exactly how the gradient carve-out over-matching
 * `radial-to-*`/`conic-to-*` (neither of which is a real Tailwind v4 utility
 * shape) went unnoticed: nothing in this file exercised the carve-out itself.
 */
function isExemptColorToken(prefix: string, token: string, shadows: Set<string>): boolean {
  const head = token.split('-')[0]
  if (BUILTIN.has(head)) return true
  if (NON_COLOR_VALUES.has(token)) return true
  if (/^opacity-\d+$/.test(token)) return true
  // v4 renamed bg-gradient-to-* to bg-linear-to-*. Deliberately NOT
  // widened to radial/conic: those families have no `-to-<direction>`
  // form at all (they are bg-radial-<angle> / bg-conic-<angle>), so
  // exempting `radial-to-br` would silently bless a class that
  // generates no CSS — a fail-open hole in the one gate that exists
  // to catch exactly that. Let them fall through to the token check.
  if (/^(?:gradient|linear)-to-(t|tr|r|br|b|bl|l|tl)$/.test(token)) return true
  // shadow-card-hover / shadow-accent / shadow-menu / shadow-drawer live
  // in --shadow-*, which is the correct namespace for them.
  if (prefix === 'shadow' && shadows.has(token)) return true
  return false
}

/** Every custom color token referenced by a utility class in source. */
function collectUsedColorTokens(): Map<string, string[]> {
  const used = new Map<string, string[]>()
  const shadows = collectDefinedShadowTokens()
  const pattern = new RegExp(
    // Prefix is now captured (group 1) so a shadow-* utility can be resolved
    // against --shadow-* before falling through to the --color-* check.
    String.raw`(?<![a-z0-9-])(${COLOR_PREFIX_ALTERNATION})-([a-z][a-z0-9]*(?:-[a-z0-9]+)*)(?![a-z0-9-])`,
    'g',
  )
  for (const file of walk(SRC)) {
    const rel = file.slice(ROOT.length + 1)
    for (const text of collectLiteralTexts(file)) {
      for (const m of text.matchAll(pattern)) {
        const prefix = m[1]
        const token = stripPositionalSegment(m[2])
        if (!token || !/^[a-z]/.test(token)) continue // bare directional utility, no color

        // Provably not a color reference — everything else falls through to the
        // defined-token check below, whatever family it claims to be.
        if (isExemptColorToken(prefix, token, shadows)) continue

        used.set(token, [...(used.get(token) ?? []), rel])
      }
    }
  }
  return used
}

/** Strip CSS comments so a var()-shaped string inside a comment can't create a false reference. */
function stripCssComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '')
}

/**
 * Every custom property defined anywhere in index.css — @theme, :root,
 * html.light, or any other block. Deliberately not scoped to one selector: a
 * property defined only under html.light (e.g. the light-mode overrides of
 * --color-bg/--color-text/etc.) still counts as defined, because the cascade
 * makes it resolve there at runtime exactly as intended.
 */
function collectDefinedCustomProperties(css: string): Set<string> {
  const defined = new Set<string>()
  for (const m of stripCssComments(css).matchAll(/(--[a-zA-Z][a-zA-Z0-9-]*)\s*:/g)) {
    defined.add(m[1])
  }
  return defined
}

/**
 * Tailwind's own reserved custom-property namespace (`--tw-*`: ring/shadow/
 * transform composition vars it writes at build time from utility classes) is
 * never declared in index.css and never should be — those are Tailwind's
 * problem, not this file's. Checked empirically: every var() reference in
 * index.css today resolves to a token this same file defines; none of them are
 * --tw-*. This set stays empty on purpose — per the finding, a raw --tw-*
 * reference must be added here BY NAME with a comment explaining why it's
 * exempt, never covered by a blanket --tw- prefix check.
 */
const TAILWIND_GENERATED_PROPERTIES = new Set<string>([])

interface VarReference {
  property: string
  fallback: string | null
  declaration: string
}

/**
 * Every `var(--x)` reference anywhere in index.css, paired with the raw
 * declaration it appeared in (for the failure message) and its fallback value,
 * if any. Declarations are found generically (`prop: value;`, value containing
 * neither `;` nor `{`/`}`) rather than scoped to any one block, so a reference
 * inside @theme itself is caught the same as one in .btn-primary — e.g.
 * `--color-primary: var(--accent)` inside @theme is exactly the shape this
 * check exists to verify, not just raw declarations in @layer components.
 */
function collectVarReferences(css: string): VarReference[] {
  const stripped = stripCssComments(css)
  const refs: VarReference[] = []
  for (const decl of stripped.matchAll(/[a-zA-Z-]+\s*:\s*[^;{}]*;/g)) {
    const declaration = decl[0].trim()
    for (const v of declaration.matchAll(/var\(\s*(--[a-zA-Z][a-zA-Z0-9-]*)\s*(,\s*[^)]*)?\)/g)) {
      refs.push({
        property: v[1],
        fallback: v[2] ? v[2].replace(/^,\s*/, '').trim() : null,
        declaration,
      })
    }
  }
  return refs
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
        // Derived from COLOR_PREFIXES (see its doc comment) rather than a
        // second hand-maintained alternation — this is exactly the list
        // collectUsedColorTokens uses for the AST scan above.
        const hit = bare.match(new RegExp(String.raw`^(?:${COLOR_PREFIX_ALTERNATION})-(.+)$`))
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

  /**
   * The AST scanner covers .ts/.tsx class names and the previous test covers
   * @apply rules, but Task 4 moved .btn-primary's background/color/box-shadow
   * (plus .btn-primary:hover and .input:focus) off @apply and onto raw CSS
   * declarations like `background: var(--accent-solid);` — a shape neither
   * existing check can see. Proven empirically: renaming --accent-solid to
   * --accent-solid-TYPO inside .btn-primary's `background` left lint,
   * type-check, every other test, and build completely green. Tailwind and
   * plain CSS both fail silently on an undefined custom property — the
   * declaration is simply dropped, no error anywhere — so this is the only
   * thing that can catch a typo'd or renamed var() in the app's primary
   * button, the single rule Task 4 exists to fix.
   */
  it('every var() reference in index.css resolves to a property defined in the file', () => {
    const css = readFileSync(resolve(SRC, 'index.css'), 'utf8')
    const defined = collectDefinedCustomProperties(css)
    const refs = collectVarReferences(css)

    const undefinedRefs = refs
      .filter((ref) => !defined.has(ref.property) && !TAILWIND_GENERATED_PROPERTIES.has(ref.property))
      .map((ref) => {
        const fallbackNote = ref.fallback ? ` (has fallback ${ref.fallback} — primary name must still resolve)` : ''
        return `${ref.property} ← ${ref.declaration}${fallbackNote}`
      })

    expect(undefinedRefs,
      'index.css references a custom property via var() that is never defined ' +
      'anywhere in this file. Tailwind and CSS both fail silently here — an ' +
      'undefined custom property produces no error, the declaration is simply ' +
      'dropped.\n\n' + undefinedRefs.join('\n'),
    ).toEqual([])
  })

  it('does not leave .btn-primary on the gray ramp', () => {
    const css = readFileSync(resolve(SRC, 'index.css'), 'utf8')
    const block = css.match(/\.btn-primary\s*\{[^}]*\}/)?.[0] ?? ''
    expect(block, '.btn-primary is live in 47 files; it must use the accent').not.toMatch(/gray-\d{3}/)
    expect(block).toMatch(/bg-primary|var\(--accent/)
  })

  it('still defines the legacy component classes (deleted in P12, not now)', () => {
    const css = readFileSync(resolve(SRC, 'index.css'), 'utf8')
    for (const cls of ['.btn', '.btn-primary', '.btn-secondary', '.input', '.card', '.badge']) {
      expect(css, `${cls} is still referenced in source`).toContain(`${cls} {`)
    }
  })

  it('keeps the PWA manifest on the current palette', () => {
    const manifest = JSON.parse(
      readFileSync(resolve(ROOT, 'public/manifest.json'), 'utf8'),
    )
    // Static file — cannot use tokens. Pinned to the DEFAULT accent's nav/bg.
    expect(manifest.background_color).toBe('#07090c')
    expect(manifest.theme_color).toBe('#0b0e13')
  })

  it('keeps index.html theme-color on the nav surface, not the old primary', () => {
    const html = readFileSync(resolve(ROOT, 'index.html'), 'utf8')
    expect(html).toContain('content="#0b0e13"')
    expect(html).not.toContain('content="#3b82f6"')
  })

  it('repalettes the offline page off the old GitHub-dark colours', () => {
    const offline = readFileSync(resolve(ROOT, 'public/offline.html'), 'utf8')
    for (const stale of ['#0d1117', '#161b22', '#30363d', '#f5f6f8', '#c9d1d9']) {
      expect(offline, `offline.html still uses ${stale}`).not.toContain(stale)
    }
    // Positively pin all four colours the page actually uses — not just the
    // background. The previous version of this guard only pinned #07090c,
    // so #f5f6f8 (body text) and #c9d1d9 (.card p text) — both stale
    // GitHub-dark hexes — shipped unconverted and unnoticed.
    expect(offline).toContain('#07090c') // body background
    expect(offline).toContain('#0f1319') // .card background
    expect(offline).toContain('#e8eaed') // body text — --color-text
    expect(offline).toContain('#cbd0d8') // .card p text — --color-text-dim
  })
})

/**
 * Direct regression coverage for isExemptColorToken's two carve-outs. Neither
 * had ever been driven by a synthetic input before — both were validated only
 * by "the rest of the suite still passes," and that gap is exactly how the
 * gradient carve-out over-matching `radial-to-*`/`conic-to-*` (not real
 * Tailwind v4 utility shapes) shipped unnoticed. These tests call the same
 * `isExemptColorToken` function collectUsedColorTokens uses — no regex is
 * re-typed here — so a future change to the real carve-out is what these
 * assertions actually exercise, not a second, driftable copy of it.
 */
describe('color-token exemption carve-outs', () => {
  const shadows = collectDefinedShadowTokens()

  it.each(['card-hover', 'accent', 'menu', 'drawer'])(
    'accepts shadow-%s (resolves against --shadow-*, not --color-*)',
    (name) => {
      expect(isExemptColorToken('shadow', name, shadows)).toBe(true)
    },
  )

  it('still rejects a misspelled shadow token (falls through to the --color-* check)', () => {
    expect(isExemptColorToken('shadow', 'crad-hover', shadows)).toBe(false)
  })

  it.each(['linear-to-br', 'gradient-to-br'])('accepts bg-%s', (token) => {
    expect(isExemptColorToken('bg', token, shadows)).toBe(true)
  })

  it('rejects bg-radial-to-br — radial has no -to-<direction> form in Tailwind v4', () => {
    expect(isExemptColorToken('bg', 'radial-to-br', shadows)).toBe(false)
  })
})

describe('non-colour token scales', () => {
  const css = readFileSync(resolve(__dirname, '../index.css'), 'utf8')
  const theme = stripCssComments(css)

  const REQUIRED = [
    '--height-btn-sm', '--height-btn-md', '--height-btn-lg',
    '--height-input-sm', '--height-input-md', '--height-input-lg',
    '--height-icon-sm', '--height-icon-md', '--height-icon-lg',
    '--z-index-nav', '--z-index-dropdown-catcher', '--z-index-dropdown',
    '--z-index-drawer-backdrop', '--z-index-drawer',
    '--ease-standard',
    '--duration-fast', '--duration-toggle', '--duration-drawer',
  ]

  it.each(REQUIRED)('defines %s', (name) => {
    expect(theme).toMatch(new RegExp(`${name}\\s*:`))
  })

  it('uses namespaces Tailwind actually recognises', () => {
    // Verified by probe build 2026-07-21: --h-* and --z-* emit the variable
    // but generate NO utility, so `h-btn-md` / `z-drawer` would silently
    // produce no CSS. Same failure mode as the 103 dead bg-warning sites.
    expect(theme).not.toMatch(/--h-(btn|input|icon)-/)
    expect(theme).not.toMatch(/--z-(nav|dropdown|drawer)/)
  })

  it('pins the z-ladder to the design §4.9 values', () => {
    const z = (n: string): string =>
      theme.match(new RegExp(`--z-index-${n}\\s*:\\s*([^;]+);`))?.[1].trim() ?? ''
    expect(z('nav')).toBe('40')
    expect(z('dropdown-catcher')).toBe('44')
    expect(z('dropdown')).toBe('45')
    expect(z('drawer-backdrop')).toBe('55')
    expect(z('drawer')).toBe('60')
  })
})

describe('interaction layer', () => {
  const css = stripCssComments(readFileSync(resolve(__dirname, '../index.css'), 'utf-8'))

  const REQUIRED_UTILITIES = [
    'ui-focus-ring', 'ui-focus-input', 'ui-disabled',
    'ui-hover-surface', 'ui-hover-solid', 'ui-hover-line',
    'ui-motion', 'ui-motion-toggle',
  ]

  /** The source text of one `@utility <name> { … }` block: from its header to
   *  the start of the next `@utility`. The interaction layer is written as one
   *  contiguous run at the end of index.css, so this needs no brace counting —
   *  and must not use a `[^}]*` capture, which would stop at the first nested
   *  rule's closing brace. */
  const utilityBlock = (name: string): string => {
    const start = css.search(new RegExp(String.raw`@utility\s+${name}(?![\w-])`))
    if (start === -1) return ''
    const rest = css.slice(start)
    const next = rest.slice(1).search(/@utility\s/)
    return next === -1 ? rest : rest.slice(0, next + 1)
  }

  /** Brace depth at every index of `text`: 0 outside any block, 1 inside one
   *  enclosing `{ }`, and so on. Used below to prove an `@utility <name>`
   *  header sits at the stylesheet root rather than nested inside some other
   *  block, e.g. `@layer components { ... }`. */
  const braceDepthAt = (text: string): number[] => {
    const depths: number[] = new Array(text.length)
    let depth = 0
    for (let i = 0; i < text.length; i++) {
      depths[i] = depth
      if (text[i] === '{') depth++
      else if (text[i] === '}') depth--
    }
    return depths
  }

  it.each(REQUIRED_UTILITIES)('defines @utility %s', (name) => {
    // The (?![\w-]) guard is what keeps `ui-motion` from matching the header
    // of `ui-motion-toggle`, and `ui-hover-surface` from matching nothing.
    expect(css).toMatch(new RegExp(String.raw`@utility\s+${name}(?![\w-])`))
  })

  /**
   * Replaces a regex that could never fail:
   *   `expect(css).not.toMatch(/@layer\s+components\s*\{[\s\S]*\.ui-focus-ring/)`
   * `@utility ui-focus-ring { ... }` contains no literal `.ui-focus-ring`
   * substring — the leading dot only ever appears in a hand-written class
   * selector — so that check matched nothing regardless of where the rule
   * actually lived, and would have stayed green even with the whole
   * interaction layer moved into @layer components.
   *
   * This walks the file tracking brace depth and asserts, per utility name,
   * both halves of "correctly placed":
   *   - its `@utility <name>` header sits at depth 0 (the stylesheet root,
   *     not nested inside @layer components or anything else), and
   *   - no `.<name>` class-selector form of it exists anywhere in the file —
   *     what a hand-rewrite into `@layer components { .ui-focus-ring { ... }
   *     }` would look like.
   *
   * Verified to discriminate, not just pass vacuously: temporarily wrapping
   * one @utility block in `@layer components { ... }` makes this test fail;
   * restoring the file makes it pass again. Both outputs are recorded in
   * p1-task-2-report.md.
   */
  it('declares them at the stylesheet root, not nested inside @layer components', () => {
    const depths = braceDepthAt(css)
    const bad: string[] = []

    for (const name of REQUIRED_UTILITIES) {
      const header = css.match(new RegExp(String.raw`@utility\s+${name}(?![\w-])`))
      const depth = header?.index !== undefined ? depths[header.index] : undefined
      if (depth !== 0) {
        bad.push(`@utility ${name} is not declared at the stylesheet root (depth: ${depth ?? 'not found'})`)
      }
      if (new RegExp(String.raw`\.${name}(?![\w-])`).test(css)) {
        bad.push(`.${name} exists as a class selector somewhere in the file`)
      }
    }

    expect(bad, bad.join('\n')).toEqual([])
  })

  const MOTION_UTILITIES = ['ui-motion', 'ui-motion-toggle']

  it.each(MOTION_UTILITIES)('collapses %s to no transition under prefers-reduced-motion', (name) => {
    const block = utilityBlock(name)
    expect(block, `@utility ${name} not found`).not.toBe('')
    const media = block.match(/@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([^}]*)\}/)
    expect(media, `${name} has no prefers-reduced-motion collapse`).not.toBeNull()
    expect(media?.[1] ?? '').toMatch(/transition\s*:\s*none/)
  })

  it('routes focus through the accent, not a hardcoded colour', () => {
    const ring = utilityBlock('ui-focus-ring')
    expect(ring).toMatch(/var\(--accent\)/)
    expect(ring).not.toMatch(/#[0-9a-f]{3,8}/i)
  })

  const OTHER_COLOR_UTILITIES = ['ui-focus-input', 'ui-hover-line', 'ui-hover-solid', 'ui-hover-surface']

  it.each(OTHER_COLOR_UTILITIES)('routes %s through --accent* or --color-*, not a hardcoded colour', (name) => {
    const block = utilityBlock(name)
    expect(block, `@utility ${name} not found`).not.toBe('')
    expect(block).toMatch(/var\(--(?:accent|color-)/)
    expect(block).not.toMatch(/#[0-9a-f]{3,8}/i)
  })
})

describe('motion utility collision tripwire', () => {
  const UI_DIR = resolve(SRC, 'components/ui')

  /**
   * ui-motion / ui-motion-toggle are not state-scoped (see the warning
   * comment above them in index.css), so each is a plain (0,1,0)
   * utility-layer rule — the same specificity as Tailwind's own transition,
   * duration and ease utilities. If a Task-4+ primitive ever carries both on
   * one element, the `transition` shorthand collision is
   * decided by Tailwind's internal emission order, not by design intent —
   * structurally the same bug class the rest of this file exists to
   * eliminate, just for `transition` instead of `border-color`.
   *
   * src/components/ui doesn't exist yet — Task 2 predates the primitives
   * Task 4 builds there — so this scan passes vacuously when the directory
   * is absent. That's an explicit, intentional existence check, not an
   * accident of a crashing glob: the moment the directory appears, this
   * test has real teeth.
   */
  it('never combines a ui-motion utility with a native transition/duration/ease utility in one class list', () => {
    if (!existsSync(UI_DIR)) return // nothing to scan yet — Task 4 creates this directory

    const MOTION_TOKENS = new Set(['ui-motion', 'ui-motion-toggle'])
    const NATIVE_MOTION_PATTERN = /(?:^|\s)(?:transition|duration|ease)-[\w-]*/

    const offenders: string[] = []
    for (const file of walk(UI_DIR)) {
      const rel = file.slice(ROOT.length + 1)
      for (const text of collectLiteralTexts(file)) {
        const hasMotionUtility = text.split(/\s+/).some((token) => MOTION_TOKENS.has(token))
        if (hasMotionUtility && NATIVE_MOTION_PATTERN.test(text)) {
          offenders.push(`${rel}: "${text.trim()}"`)
        }
      }
    }

    expect(offenders,
      'A className combines a ui-motion utility with a native Tailwind ' +
      'transition-*/duration-*/ease-* utility. Both are equal-specificity ' +
      '(0,1,0) rules with no state scoping, so the `transition` shorthand ' +
      'collision has no deterministic winner. Use var(--duration-*) / ' +
      'var(--ease-*) directly, or drop the native utility.\n\n' +
      offenders.join('\n'),
    ).toEqual([])
  })
})
