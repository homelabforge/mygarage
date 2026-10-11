/**
 * A tread depth typed as decimal inches into a thirty-seconds field.
 *
 * Tread in `in32` is entered as a count of thirty-seconds (`11` means 11/32
 * in). A digital tread gauge reads in decimal inches, though, and a user who
 * types the gauge's `0.346` into that field stored 0.346/32 in: about 0.27 mm,
 * a tire reading as bald (it rendered `0/32 in`) that was really at 11/32.
 *
 * Reading the entry as inches is safe only below 1. A count of thirty-seconds
 * between 0 and 1 is not a depth anyone measures (the smallest step on a
 * stick gauge is 1/32), while a decimal-inch tread on a car or light-truck
 * tire never reaches a whole inch. Zero and every whole number keep meaning
 * thirty-seconds, so nothing that already worked changes. A millimetre user is
 * never touched: a decimal is an ordinary millimetre value.
 *
 * The conversion goes through the tread formatter, not a factor of 32 written
 * here: inches to canonical millimetres with `UnitConverter`'s own inch, then
 * `toInputValue` renders that in thirty-seconds at the unit's precision, so
 * 0.346 in lands on the nearest 32nd, `11`, the same way every other value in
 * the field is rounded.
 */

import type { QuantityFormat } from './unitFormat'
import { UnitConverter } from './units'

/** Millimetres per metre: canonical tread is millimetres, the inch is in metres. */
const MM_PER_M = 1000

/**
 * The thirty-seconds a decimal-inch tread entry means, or null when it means itself.
 *
 * @param typed The field's text as typed.
 * @param tread The client's tread formatter, from `useUnitFormat()`.
 * @returns The entry rewritten in thirty-seconds, e.g. `'11'` for `'.346'`;
 *   null when the unit is not `in32` or the entry is not strictly between 0
 *   and 1, so the caller keeps what was typed.
 */
export function thirtySecondsFromDecimalInches(
  typed: string,
  tread: QuantityFormat
): string | null {
  if (tread.unit !== 'in32' || typed.trim() === '') return null
  const inches = Number(typed)
  if (!Number.isFinite(inches) || inches <= 0 || inches >= 1) return null
  return tread.toInputValue(inches * UnitConverter.INCH_TO_METERS * MM_PER_M)
}

/**
 * A tread field's text as it should be saved: decimal inches rewritten, anything else as typed.
 *
 * Save paths call this as well as the field's blur, so a value typed and saved
 * without the field ever losing focus is still read as inches.
 *
 * @param typed The field's text as typed.
 * @param tread The client's tread formatter.
 * @returns The text to hand to `canonicalFromUnitField`.
 */
export function normaliseTreadEntry(typed: string, tread: QuantityFormat): string {
  return thirtySecondsFromDecimalInches(typed, tread) ?? typed
}
