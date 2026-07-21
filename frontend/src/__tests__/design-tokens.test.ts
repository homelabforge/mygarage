import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve, join } from 'node:path'

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
const NON_COLOR_VALUES = new Set([
  'xs', 'sm', 'md', 'lg', 'xl', '2xl', '3xl',
  'base', 'center', 'left', 'right', 'none', 'hidden',
  'dashed', 'solid', 'double', 'collapse', 'separate', 'cover', 'contain',
  'radius', 'anchor',
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
 * Tailwind classes never live inside a comment. Stripping comments before
 * scanning removes prose that only coincidentally reads like a utility class —
 * a line comment mentioning "fill-ups", a doc comment describing "text-based"
 * behavior — without hiding anything a generated class could actually appear in.
 */
function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(?<!:)\/\/.*$/gm, ' ')
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
    const src = stripComments(readFileSync(file, 'utf8'))
    for (const m of src.matchAll(pattern)) {
      const token = stripPositionalSegment(m[1])
      if (!token || !/^[a-z]/.test(token)) continue // bare directional utility, no color

      // Provably not a color reference — everything else falls through to the
      // defined-token check below, whatever family it claims to be.
      const head = token.split('-')[0]
      if (BUILTIN.has(head)) continue
      if (NON_COLOR_VALUES.has(token)) continue
      if (/^opacity-\d+$/.test(token)) continue
      if (/^gradient-to-(t|tr|r|br|b|bl|l|tl)$/.test(token)) continue

      const rel = file.slice(ROOT.length + 1)
      used.set(token, [...(used.get(token) ?? []), rel])
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
})
