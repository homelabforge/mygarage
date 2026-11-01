/**
 * Locale-aware parsing of a hand-typed decimal.
 *
 * Deliberately locale-INDEPENDENT wherever the input allows it, so a Polish
 * user typing "528.25" out of habit and an English user typing "528,25" both
 * get what they meant. Locale is consulted for exactly one shape: a single
 * separator followed by exactly three digits ("1,234"), which is simultaneously
 * a legal thousands group and a legal three-place decimal. That case is
 * resolved by locale AND reported via `ambiguous` so the UI can show its
 * reading — a wrong guess on an odometer is a 1000x error.
 *
 * Returns a discriminated result so callers can tell EMPTY from INVALID. The
 * previous behaviour collapsed both to `undefined`, silently discarding bad
 * input on save.
 */

import { getActiveLocale } from '@/constants/i18n'

export type DecimalParseResult =
  | { kind: 'empty' }
  | { kind: 'value'; value: number; ambiguous: boolean }
  | { kind: 'invalid' }

/**
 * Grouping characters people type or paste.
 *
 * `\s` already covers NBSP (U+00A0) and narrow NBSP (U+202F) — verified — so do
 * NOT add those as literal characters. Invisible characters in a character
 * class survive neither code review nor copy-paste reliably.
 */
const GROUPING_CHARS = /[\s']/g

/** Anything that is not a digit, separator or sign — currency symbols, stray letters. */
const NON_NUMERIC = /[^\d.,+-]/g

/** A well-formed thousands grouping: first group 1-3 digits, every later group exactly 3. */
const groupingWellFormed = (parts: string[]): boolean =>
  parts[0] !== '' && parts[0].length <= 3 && parts.slice(1).every(p => p.length === 3)

const separators = new Map<string, string>()

/**
 * The character this locale writes a decimal point with.
 *
 * Cached because `parseDecimalInput` reaches it on the ambiguous-separator path,
 * which means once per keystroke in every `NumberInput` on screen, and it built a
 * whole `Intl.NumberFormat` each time only to read ONE character out of it. The
 * RESULT is cached rather than the formatter (so this does not use
 * `numberFormatCache`): a single character is cheaper to keep than the machine
 * that produced it, and nothing else here needs that machine.
 *
 * Keyed on the locale, which is the only thing the answer depends on.
 */
export function localeDecimalSeparator(locale: string): string {
  const cached = separators.get(locale)
  if (cached !== undefined) return cached
  const parts = new Intl.NumberFormat(locale).formatToParts(1.1)
  const separator = parts.find(p => p.type === 'decimal')?.value ?? '.'
  separators.set(locale, separator)
  return separator
}

export function parseDecimalInput(raw: string, locale: string): DecimalParseResult {
  if (typeof raw !== 'string') return { kind: 'invalid' }

  const trimmed = raw.trim()
  if (trimmed === '') return { kind: 'empty' }

  // Reject scientific notation outright: stripping the exponent character would
  // turn "1e5" into "15", and silently wrong is worse than rejected.
  if (/[eE]/.test(trimmed)) return { kind: 'invalid' }

  let s = trimmed.replace(GROUPING_CHARS, '').replace(NON_NUMERIC, '')
  if (s === '') return { kind: 'invalid' }

  let sign = 1
  if (s.startsWith('-')) {
    sign = -1
    s = s.slice(1)
  } else if (s.startsWith('+')) {
    s = s.slice(1)
  }
  if (s === '' || /[+-]/.test(s)) return { kind: 'invalid' }

  const dots = (s.match(/\./g) ?? []).length
  const commas = (s.match(/,/g) ?? []).length

  let normalized: string
  let ambiguous = false

  if (dots === 0 && commas === 0) {
    normalized = s
  } else if (dots > 0 && commas > 0) {
    // Both kinds present: the LAST is the decimal point, the other groups.
    const decimal = s.lastIndexOf('.') > s.lastIndexOf(',') ? '.' : ','
    const grouping = decimal === '.' ? ',' : '.'
    if ((decimal === '.' ? dots : commas) > 1) return { kind: 'invalid' }

    const [intPart, fracPart] = s.split(decimal)
    // [rev2] the grouping character may appear ONLY in the integer part, and
    // only as exact three-digit groups. Without this, "12,34.56" parsed as
    // 1234.56 instead of being rejected.
    if (fracPart.includes(grouping)) return { kind: 'invalid' }
    const groups = intPart.split(grouping)
    if (!groupingWellFormed(groups)) return { kind: 'invalid' }
    normalized = groups.join('') + '.' + fracPart
  } else {
    const separator = dots > 0 ? '.' : ','
    const count = dots > 0 ? dots : commas
    const parts = s.split(separator)

    if (count > 1) {
      // One kind repeated: only a grouping reading is possible.
      if (!groupingWellFormed(parts)) return { kind: 'invalid' }
      normalized = parts.join('')
    } else {
      // Exactly one separator. A grouping reading is possible only if the
      // groups are well formed AND the tail is exactly three digits.
      const groupingReadingValid = groupingWellFormed(parts) && parts[1].length === 3
      if (groupingReadingValid) {
        // Both readings are legal — this is the ambiguous shape.
        ambiguous = true
        normalized =
          localeDecimalSeparator(locale) === separator ? parts.join('.') : parts.join('')
      } else {
        normalized = parts.join('.')
      }
    }
  }

  if (normalized === '' || normalized === '.') return { kind: 'invalid' }
  if (!/^\d*\.?\d*$/.test(normalized)) return { kind: 'invalid' }

  const value = Number(normalized)
  if (!Number.isFinite(value)) return { kind: 'invalid' }

  return { kind: 'value', value: sign * value, ambiguous }
}

/**
 * The value of a controlled numeric field, or `undefined` when it is empty or
 * not a number. For fields whose empty and invalid states both mean "no
 * value" (an optional interval, a cost); a field that must tell them apart
 * calls `parseDecimalInput` itself.
 */
export function parseOptionalDecimal(raw: string): number | undefined {
  const result = parseDecimalInput(raw, getActiveLocale())
  return result.kind === 'value' ? result.value : undefined
}

/**
 * A controlled field's text as the number a form holds: blank is `undefined`,
 * and text that isn't a number is NaN, so the form's own check can say so
 * instead of the entry quietly going away.
 */
export function readTypedNumber(raw: string): number | undefined {
  const result = parseDecimalInput(raw, getActiveLocale())
  if (result.kind === 'empty') return undefined
  return result.kind === 'value' ? result.value : Number.NaN
}

/**
 * A controlled box's text as a payload number, read in the user's language.
 * Blank is null, and so is text that isn't a number, so check `firstUnreadable`
 * before the save or that text quietly saves as blank.
 */
export function numberFromField(raw: string): number | null {
  const result = parseDecimalInput(raw, getActiveLocale())
  return result.kind === 'value' ? result.value : null
}

/** A box to check before a save: its label, and its text or `false` when it isn't shown. */
export type LabelledNumberText = readonly [label: string, text: string | false]

/** The label of the first box holding text that isn't a number. Blank is fine. */
export function firstUnreadable(fields: readonly LabelledNumberText[]): string | undefined {
  return fields.find(
    ([, text]) => text !== false && parseDecimalInput(text, getActiveLocale()).kind === 'invalid'
  )?.[0]
}
