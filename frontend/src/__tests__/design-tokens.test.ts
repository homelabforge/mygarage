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

/** Every custom color token referenced by a utility class in source. */
function collectUsedColorTokens(): Map<string, string[]> {
  const used = new Map<string, string[]>()
  const pattern = new RegExp(
    String.raw`\b(?:${COLOR_PREFIXES.join('|')})-([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\b`,
    'g',
  )
  for (const file of walk(SRC)) {
    const src = readFileSync(file, 'utf8')
    for (const m of src.matchAll(pattern)) {
      const token = m[1]
      // Skip Tailwind's built-in palettes and non-color utilities that share a prefix.
      const head = token.split('-')[0]
      if (BUILTIN.has(head)) continue
      if (!/^(garage|primary|success|warning|danger|accent|surface|text|border|hair|nav|bg)\b/.test(token)) continue
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
