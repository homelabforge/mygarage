import { getActiveLocale } from '../constants/i18n'
import { numberFromField } from './decimalInput'

/**
 * An engine-hours figure as the tire screens show it: one decimal, grouped
 * in the selected language, and a fixed "hr" (hours have no unit preference).
 */
export function formatHours(value: number | string): string {
  const n = typeof value === 'string' ? Number(value) : value
  const shown = new Intl.NumberFormat(getActiveLocale(), {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(n)
  return `${shown} hr`
}

/** An hour meter field as typed, for a payload: blank is null, 0 stays 0, and "812,5" reads in de. */
export function hoursFromField(typed: string): number | null {
  return numberFromField(typed)
}
