import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'

const ROOT = resolve(__dirname, '../..')

/**
 * Fontsource variable packages ship ONE stylesheet per axis containing an
 * @font-face per subset, each with its own unicode-range and woff2 file — they
 * do NOT ship per-subset entry points. That is better than importing subsets
 * individually: the browser downloads only the ranges a page actually uses, so
 * Cyrillic coverage costs a latin-only user nothing.
 *
 * So we assert on the *resolved glyph coverage*, not on import strings. Cyrillic
 * is load-bearing — `ru` and `uk` are shipped locales, and losing that subset
 * drops them to fallback glyphs mid-sentence.
 */
const REQUIRED_RANGES: Record<string, string> = {
  latin: 'U+0000-00FF',
  'latin-ext': 'U+0100-02BA',
  cyrillic: 'U+0400-045F',
  'cyrillic-ext': 'U+0460-052F',
}

const FAMILIES = {
  inter: { pkg: '@fontsource-variable/inter', family: 'Inter Variable' },
  mono: { pkg: '@fontsource-variable/jetbrains-mono', family: 'JetBrains Mono Variable' },
} as const

describe('font loading', () => {
  const css = readFileSync(resolve(ROOT, 'src/styles/fonts.css'), 'utf8')

  it.each(Object.values(FAMILIES))('imports $pkg', ({ pkg }) => {
    expect(css).toContain(pkg)
  })

  describe.each(Object.values(FAMILIES))('$family', ({ pkg, family }) => {
    const resolved = readFileSync(resolve(ROOT, 'node_modules', pkg, 'index.css'), 'utf8')

    it('declares the family name the theme tokens reference', () => {
      expect(resolved).toContain(`font-family: '${family}'`)
    })

    it.each(Object.entries(REQUIRED_RANGES))('covers the %s subset', (_name, range) => {
      expect(resolved).toContain(range)
    })

    it('uses font-display: swap', () => {
      expect(resolved).toContain('font-display: swap')
    })
  })

  it('installs both font packages', () => {
    const pkg = JSON.parse(readFileSync(resolve(ROOT, 'package.json'), 'utf8'))
    expect(pkg.dependencies).toHaveProperty('@fontsource-variable/inter')
    expect(pkg.dependencies).toHaveProperty('@fontsource-variable/jetbrains-mono')
  })

  it('is imported by the app entrypoint', () => {
    const main = readFileSync(resolve(ROOT, 'src/main.tsx'), 'utf8')
    expect(main).toContain("import './styles/fonts.css'")
  })

  it('never serves fonts from public/ (would 404 under a subpath)', () => {
    expect(existsSync(resolve(ROOT, 'public/fonts'))).toBe(false)
  })
})
