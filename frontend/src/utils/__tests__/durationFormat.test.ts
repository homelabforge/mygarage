import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setActiveLocale } from '@/constants/i18n'
import { formatDuration } from '@/utils/durationFormat'

/**
 * The LiveLink tabs' durations, in the reader's language.
 *
 * Two engines answer: `Intl.DurationFormat` where the browser has it, and a
 * per-unit `Intl.NumberFormat` fallback where it doesn't (Chrome < 129,
 * Firefox < 136). They don't agree on the joiner (`de` DurationFormat uses the
 * locale's list pattern, `1h, 0 Min.`, the fallback a space), so each engine is
 * pinned against its own table rather than one table for both.
 */

const INPUTS = [0, 5, 60, 3600, 3661] as const

interface Table {
  plain: readonly string[]
  seconds: readonly string[]
}

// Index-aligned with INPUTS. Measured on Node 24.21.
const DURATION_FORMAT: Record<'en' | 'de', Table> = {
  en: {
    plain: ['0m', '0m', '1m', '1h 0m', '1h 1m'],
    seconds: ['0s', '5s', '1m 0s', '1h 0m', '1h 1m'],
  },
  de: {
    plain: ['0 Min.', '0 Min.', '1 Min.', '1h, 0 Min.', '1h, 1 Min.'],
    seconds: ['0 Sek.', '5 Sek.', '1 Min., 0 Sek.', '1h, 0 Min.', '1h, 1 Min.'],
  },
}

const NUMBER_FORMAT: Record<'en' | 'de', Table> = {
  en: {
    plain: ['0m', '0m', '1m', '1h 0m', '1h 1m'],
    seconds: ['0s', '5s', '1m 0s', '1h 0m', '1h 1m'],
  },
  de: {
    plain: ['0 Min.', '0 Min.', '1 Min.', '1h 0 Min.', '1h 1 Min.'],
    seconds: ['0 Sek.', '5 Sek.', '1 Min. 0 Sek.', '1h 0 Min.', '1h 1 Min.'],
  },
}

function expectTable(table: Record<'en' | 'de', Table>): void {
  for (const lang of ['en', 'de'] as const) {
    setActiveLocale(lang)
    expect(INPUTS.map((s) => formatDuration(s)), `${lang} plain`).toEqual(table[lang].plain)
    expect(
      INPUTS.map((s) => formatDuration(s, { seconds: true })),
      `${lang} seconds`
    ).toEqual(table[lang].seconds)
  }
}

afterEach(() => setActiveLocale('en'))

describe('formatDuration with Intl.DurationFormat', () => {
  beforeEach(() => {
    // Without it this block would quietly test the fallback.
    expect(typeof Intl.DurationFormat, 'engine has Intl.DurationFormat').toBe('function')
  })

  it("keeps the tabs' shapes, zero units shown, in en and de", () => {
    expectTable(DURATION_FORMAT)
  })

  it('reads a missing duration as the absent marker', () => {
    expect(formatDuration(null)).toBe('--')
    expect(formatDuration(undefined)).toBe('--')
    expect(formatDuration(null, { seconds: true })).toBe('--')
  })

  it('follows a language switch instead of answering the first language forever', () => {
    setActiveLocale('en')
    expect(formatDuration(3661)).toBe('1h 1m')
    setActiveLocale('de')
    expect(formatDuration(3661)).toBe('1h, 1 Min.')
    setActiveLocale('en')
    expect(formatDuration(3661)).toBe('1h 1m')
  })
})

describe('formatDuration without Intl.DurationFormat (older browsers)', () => {
  let saved: PropertyDescriptor | undefined

  beforeEach(() => {
    saved = Object.getOwnPropertyDescriptor(Intl, 'DurationFormat')
    Reflect.deleteProperty(Intl, 'DurationFormat')
    expect(typeof Intl.DurationFormat, 'Intl.DurationFormat deleted').toBe('undefined')
  })
  afterEach(() => {
    if (saved) Object.defineProperty(Intl, 'DurationFormat', saved)
  })

  it('keeps the same shapes through per-unit NumberFormat, in en and de', () => {
    expectTable(NUMBER_FORMAT)
  })

  it('reads a missing duration as the absent marker', () => {
    expect(formatDuration(null)).toBe('--')
    expect(formatDuration(undefined, { seconds: true })).toBe('--')
  })

  it('follows a language switch', () => {
    setActiveLocale('en')
    expect(formatDuration(65, { seconds: true })).toBe('1m 5s')
    setActiveLocale('de')
    expect(formatDuration(65, { seconds: true })).toBe('1 Min. 5 Sek.')
  })
})
