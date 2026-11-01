import { describe, it, expect } from 'vitest'
import { scanSource } from '../../scripts/validate-hardcoded-strings'

// Fixtures go through the gate's real per-file scan (line scanner plus
// multiline scanner), so a hit can't hide in the seam between the two.
const scan = (source: string): string[] =>
  scanSource(source, 'fixture.tsx', true).map((f) => f.text)

describe('validate-hardcoded-strings: JSX text beside an {expression}', () => {
  it('flags both halves of text split by an interpolation on one line', () => {
    // The DEF tile shipped exactly this and the gate never saw it (G2c-60).
    const texts = scan('<span>Est. {u.distance.label} Left</span>\n')
    expect(texts).toContain('Est.')
    expect(texts).toContain('Left')
  })

  it('flags text sitting between two expressions on one line', () => {
    expect(scan('<p>{count} items remaining {suffix}</p>\n')).toEqual(['items remaining'])
  })

  it('counts a capitalised abbreviation with a dot as prose', () => {
    expect(scan('<span>Est. {value}</span>\n')).toEqual(['Est.'])
  })

  // Guards: these pass on main too. Mutations that turn them red are in
  // task-10-report.md.
  it('reports plain >text< once, not once per scanner', () => {
    expect(scan('<p>Hello there friend</p>\n')).toEqual(['Hello there friend'])
  })

  it('ignores a TS assertion after an object literal', () => {
    expect(scan('const m = ({ a: 1 } as Record<string, number>)\n')).toEqual([])
    expect(scan('const m = {\n  a: 1,\n} as Record<string, number>\n')).toEqual([])
  })

  it('keeps prose that happens to read "as Something" after an expression', () => {
    expect(scan('<p>Signed in {name} as Owner</p>\n')).toEqual(['Signed in', 'as Owner'])
  })

  it('still honours i18n-exempt on the line above', () => {
    expect(scan('// i18n-exempt\n<span>Est. {x} Left</span>\n')).toEqual([])
  })
})
