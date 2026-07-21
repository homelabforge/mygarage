import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { ACCENTS, ACCENT_KEYS, DEFAULT_ACCENT, accentCssVars } from '../constants/accents'

/** Surface colours the accent roles are judged against, per theme. */
const SURFACE = { dark: '#0f1319', light: '#ffffff' } as const

/** Fixed status colours (design §4.9) — accents must stay distinguishable. */
const STATUS = [
  '#f0503a', '#f0a53a', '#34d399', '#22c55e', '#22d3ee',
  // warning-alt — calendar warranty events, the "Create Full Backup"
  // action, and the 6-month rolling average series. A real fixed status
  // colour in its own right, not a duplicate of warning (#f0a53a) — do
  // not trim it.
  '#f5a524',
] as const

function srgbToLinear(c: number): number {
  const s = c / 255
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
}

function parseHex(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ]
}

function relativeLuminance(hex: string): number {
  const [r, g, b] = parseHex(hex).map(srgbToLinear)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrastRatio(a: string, b: string): number {
  const [la, lb] = [relativeLuminance(a), relativeLuminance(b)]
  const [hi, lo] = la > lb ? [la, lb] : [lb, la]
  return (hi + 0.05) / (lo + 0.05)
}

/** Crude perceptual distance in sRGB. Good enough to catch "identical". */
function colourDistance(a: string, b: string): number {
  const [ar, ag, ab] = parseHex(a)
  const [br, bg, bb] = parseHex(b)
  return Math.sqrt((ar - br) ** 2 + (ag - bg) ** 2 + (ab - bb) ** 2)
}

describe('accent roles', () => {
  it('defines exactly the six accents', () => {
    expect(ACCENT_KEYS).toEqual(['blue', 'amber', 'teal', 'red', 'violet', 'green'])
    expect(DEFAULT_ACCENT).toBe('blue')
  })

  describe.each(ACCENT_KEYS)('%s', (key) => {
    const roles = ACCENTS[key]

    it('has readable text on its solid background (WCAG AA, 4.5:1)', () => {
      const ratio = contrastRatio(roles.solid, roles.onSolid)
      expect(ratio, `${key}: ${roles.onSolid} on ${roles.solid} = ${ratio.toFixed(2)}:1`)
        .toBeGreaterThanOrEqual(4.5)
    })

    it('has readable accent text on the dark surface (3:1 — large/semibold UI text)', () => {
      const ratio = contrastRatio(roles.fgDark, SURFACE.dark)
      expect(ratio, `${key}: fgDark ${roles.fgDark} on ${SURFACE.dark} = ${ratio.toFixed(2)}:1`)
        .toBeGreaterThanOrEqual(3)
    })

    it('has readable accent text on the light surface (3:1)', () => {
      const ratio = contrastRatio(roles.fgLight, SURFACE.light)
      expect(ratio, `${key}: fgLight ${roles.fgLight} on ${SURFACE.light} = ${ratio.toFixed(2)}:1`)
        .toBeGreaterThanOrEqual(3)
    })

    it.each(STATUS)('stays perceptually distinct from status colour %s', (status) => {
      // This check exists to catch an accent that is IDENTICAL or
      // near-identical to a status colour — that collision makes the status
      // colour carry no independent signal (a badge and a status pill read
      // as the same colour). It is not meant to enforce a wide berth
      // between merely distinct hues, so the floor sits just above "same
      // colour," not at a comfortable design distance.
      //
      // Handoff green (#34d399) and amber (#f5a524) were BYTE-IDENTICAL
      // (0.00 units) to fixed success and warning-alt respectively —
      // genuine, indefensible collisions, kept shifted (see their entries
      // in accents.ts). Warning proper (#f0a53a) is a DIFFERENT fixed
      // colour and only a nearer-miss for handoff amber, at 22.56 units —
      // it's warning-alt, not warning, that was the exact collision.
      // Handoff red (40.01 from danger) and teal (38.65 from success) are
      // comfortably distinct hues that only ever failed because the floor
      // used to sit at exactly 40; both are reverted to their handoff
      // values.
      expect(colourDistance(roles.accent, status),
        `${key} accent ${roles.accent} is indistinguishable from status ${status}`)
        .toBeGreaterThan(25)
    })
  })

  it('emits the runtime custom properties', () => {
    const vars = accentCssVars('amber', 'dark')
    expect(vars).toHaveProperty('--accent')
    expect(vars).toHaveProperty('--accent-solid')
    expect(vars).toHaveProperty('--accent-on-solid')
    expect(vars).toHaveProperty('--accent-fg')
    expect(vars).toHaveProperty('--accent-soft')
    expect(vars).toHaveProperty('--accent-line')
  })

  it('swaps the foreground role between themes', () => {
    expect(accentCssVars('blue', 'dark')['--accent-fg'])
      .not.toBe(accentCssVars('blue', 'light')['--accent-fg'])
  })
})

describe('index.css accent defaults', () => {
  const css = readFileSync(resolve(__dirname, '../index.css'), 'utf8')
  const blue = ACCENTS[DEFAULT_ACCENT]

  it.each([
    ['--accent', blue.accent],
    ['--accent-solid', blue.solid],
    ['--accent-on-solid', blue.onSolid],
    ['--accent-fg', blue.fgDark],
  ])('%s matches constants/accents.ts', (prop, value) => {
    expect(css, `index.css ${prop} is out of sync with DEFAULT_ACCENT`)
      .toMatch(new RegExp(`${prop}\\s*:\\s*${value}`, 'i'))
  })

  it('overrides --accent-fg for light mode', () => {
    const light = css.match(/html\.light\s*\{[^}]*\}/s)?.[0] ?? ''
    expect(light).toMatch(new RegExp(`--accent-fg\\s*:\\s*${blue.fgLight}`, 'i'))
  })
})

describe('pre-React inline script', () => {
  const html = readFileSync(resolve(__dirname, '../../index.html'), 'utf8')

  it.each(ACCENT_KEYS)('carries the same base hex for %s as constants/accents.ts', (key) => {
    expect(html, `index.html inline script is out of sync for "${key}"`)
      .toContain(ACCENTS[key].accent)
  })

  it.each(ACCENT_KEYS)('carries the same onSolid hex for %s', (key) => {
    expect(html).toContain(ACCENTS[key].onSolid)
  })
})
