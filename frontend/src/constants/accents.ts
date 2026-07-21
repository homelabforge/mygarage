/**
 * The six user-selectable accents.
 *
 * One base colour cannot serve as text, as a solid background, and as a border:
 * the prototype's six accents run 1.86:1-3.67:1 against white, so `bg-primary
 * text-white` (live in Layout.tsx and Register.tsx) is unreadable for amber,
 * teal and green. Each accent therefore carries five roles, gated by
 * src/__tests__/accent-contrast.test.ts.
 *
 * - accent   base hue: borders, underlines, icon glyphs, chart series
 * - solid    solid button/badge background
 * - onSolid  text/icons ON solid — dark ink for light accents
 * - fgDark   accent-coloured TEXT on the dark surface
 * - fgLight  accent-coloured TEXT on the light surface (darkened base)
 * - soft/line 15% and 45% tonal fills, derived from `accent`
 */
export type AccentKey = 'blue' | 'amber' | 'teal' | 'red' | 'violet' | 'green'

export const ACCENT_KEYS: readonly AccentKey[] = [
  'blue', 'amber', 'teal', 'red', 'violet', 'green',
] as const

export const DEFAULT_ACCENT: AccentKey = 'blue'

export interface AccentRoles {
  accent: string
  solid: string
  onSolid: string
  fgDark: string
  fgLight: string
  soft: string
  line: string
}

export const ACCENTS: Record<AccentKey, AccentRoles> = {
  blue: {
    accent: '#4f8cff', solid: '#2f6fe4', onSolid: '#ffffff',
    fgDark: '#7aa8ff', fgLight: '#1d4ed8',
    soft: 'rgba(79,140,255,.15)', line: 'rgba(79,140,255,.45)',
  },
  amber: {
    // Two deviations from the handoff's #f5a524, both forced by
    // accent-contrast.test.ts:
    //  - onSolid exists at all because white text on #f5a524 is ~2:1; the
    //    prototype's own fixed amber button already uses dark ink here.
    //  - #f5a524 is only 22.6 perceptual units from the fixed warning colour
    //    #f0a53a (they differ by R+5/G+0/B-22) — functionally the same hue,
    //    which would make an amber accent read as a warning badge. Moved
    //    accent+solid to #f9aa0b (H37→40°, S91%→95%, L55%→51%): 48.1 units
    //    from warning, the tightest of amber's five status gaps. fgDark/
    //    fgLight are untouched — SURFACE-relative, not status-relative, so
    //    the hue nudge doesn't affect them.
    accent: '#f9aa0b', solid: '#f9aa0b', onSolid: '#3a2600',
    fgDark: '#f7b953', fgLight: '#92600a',
    soft: 'rgba(249,170,11,.15)', line: 'rgba(249,170,11,.45)',
  },
  teal: {
    // accent (only) moved #2dd4bf→#38d6c6 — L 50.4%→53%, same hue/sat. The
    // handoff value sat 38.65 units from fixed success #34d399, just under
    // the 40 floor; teal's usable hue corridor between success (158°) and
    // info (188°) is only 30° wide, so this is deliberately the smallest
    // nudge that clears both edges (45.3 from success, 45.8 from info) —
    // visually indistinguishable from the original. solid/onSolid/fgDark/
    // fgLight are the handoff's values unchanged; none of them are gated
    // against STATUS, only against each other or SURFACE, and all already
    // passed.
    accent: '#38d6c6', solid: '#2dd4bf', onSolid: '#04231d',
    fgDark: '#5ce0d0', fgLight: '#0f766e',
    soft: 'rgba(56,214,198,.15)', line: 'rgba(56,214,198,.45)',
  },
  red: {
    // Shifted from the prototype's #f43f5e toward magenta so it stays distinct
    // from danger #f0503a; a Racing Red that reads as "overdue" is a bug.
    accent: '#fb3b6d', solid: '#d81e52', onSolid: '#ffffff',
    fgDark: '#ff6f92', fgLight: '#be123c',
    soft: 'rgba(251,59,109,.15)', line: 'rgba(251,59,109,.45)',
  },
  violet: {
    accent: '#a78bfa', solid: '#7c5cf0', onSolid: '#ffffff',
    fgDark: '#bda6ff', fgLight: '#6d28d9',
    soft: 'rgba(167,139,250,.15)', line: 'rgba(167,139,250,.45)',
  },
  green: {
    // The handoff's #34d399 IS the fixed success colour (byte-identical), so
    // the plan's first-pass fix moved it to #3ecf8e — but that only bought
    // 15.4 units, still short of the 40 floor, because true green is boxed in
    // on BOTH sides: fixed success sits at H158° and STATUS also includes
    // Tailwind green-500 (#22c55e, H142°) as a distinguishability floor, a
    // mere 16° corridor with no room for a third green. Rather than split
    // that gap, accent+solid moved out of it entirely to H138° (#51cd76,
    // S55%/L56%) — 45.9 units from success, 53.4 from green-500, and still
    // unambiguously "green" rather than crossing into teal or lime. solid
    // darkened in step (H138 L32% → #257e40) because the handoff's #1f9d64
    // was 3.46:1 against white, short of the 4.5:1 AA floor; #257e40 clears
    // it at 5.08:1. fgDark/fgLight re-derived at the same H138 hue
    // (#88dda2 / #22773c) rather than kept at the old ~H150 tint/shade, so
    // text and border/solid read as the same green instead of two.
    accent: '#51cd76', solid: '#257e40', onSolid: '#ffffff',
    fgDark: '#88dda2', fgLight: '#22773c',
    soft: 'rgba(81,205,118,.15)', line: 'rgba(81,205,118,.45)',
  },
}

/** i18n keys — never English literals; the hardcoded-strings gate would flag them. */
export const ACCENT_LABEL_KEYS: Record<AccentKey, string> = {
  blue: 'settings:accent.blue',
  amber: 'settings:accent.amber',
  teal: 'settings:accent.teal',
  red: 'settings:accent.red',
  violet: 'settings:accent.violet',
  green: 'settings:accent.green',
}

/**
 * The custom properties written to document.documentElement.
 * Never set these on a descendant element: @theme resolves `--color-primary:
 * var(--accent)` against :root, so a child cannot re-resolve it — the ~589
 * *-primary utilities would stay blue while focus rings switched.
 */
export function accentCssVars(
  key: AccentKey,
  theme: 'light' | 'dark',
): Record<string, string> {
  const r = ACCENTS[key] ?? ACCENTS[DEFAULT_ACCENT]
  return {
    '--accent': r.accent,
    '--accent-solid': r.solid,
    '--accent-on-solid': r.onSolid,
    '--accent-fg': theme === 'light' ? r.fgLight : r.fgDark,
    '--accent-soft': r.soft,
    '--accent-line': r.line,
  }
}
