/**
 * A digital gauge's decimal inches typed into a /32 in tread field.
 *
 * Only an entry strictly between 0 and 1 is read as inches: no stick gauge
 * reads a fraction of a 32nd, and no car tire has an inch of tread. Zero, whole
 * 32nds and every millimetre entry stay as typed.
 */

import { numberFromField } from './decimalInput'
import { canonicalFromTypedUnitField, type QuantityFormat, type UnitFieldOrigin } from './unitFormat'
import { UnitConverter } from './units'

/** Canonical tread is millimetres; the inch factor is in metres. */
const MM_PER_M = 1000

/**
 * The number a gauge-shaped entry ("0.346" or ".346") reads as, or null for anything else.
 *
 * A leading zero is never a thousands group, so that's a decimal with either
 * separator in any language; de would otherwise read 0.346 as 346.
 */
export function gaugeDecimal(typed: string): number | null {
  const gauge = /^\s*0?[.,](\d+)\s*$/.exec(typed)
  return gauge ? Number(`0.${gauge[1]}`) : null
}

/**
 * The 32nds a decimal-inch entry means, or null when the entry means itself.
 *
 * Rounded by the field's own formatter, so 0.346 lands on 11 the way any value does.
 */
export function thirtySecondsFromDecimalInches(
  typed: string,
  tread: QuantityFormat
): string | null {
  if (tread.unit !== 'in32') return null
  // Anything not gauge-shaped reads in the user's language.
  const inches = gaugeDecimal(typed) ?? numberFromField(typed)
  if (inches === null || inches <= 0 || inches >= 1) return null
  return tread.toInputValue(inches * UnitConverter.INCH_TO_METERS * MM_PER_M)
}

/**
 * A tread field's canonical value, with a gauge's decimal inches read as a new measurement.
 *
 * A converted entry skips the origin. 8.40 mm seeds the field as 11 and 0.346 in
 * is 11 too, so going through the origin would keep the old 8.40 for a reading
 * the user just took. Anything else goes through `canonicalFromTypedUnitField`,
 * which reads the box's text in the user's language.
 */
export function canonicalFromTreadField(
  typed: string,
  origin: UnitFieldOrigin,
  tread: QuantityFormat
): number | null {
  const thirtySeconds = thirtySecondsFromDecimalInches(typed, tread)
  if (thirtySeconds !== null) return tread.toCanonical(Number(thirtySeconds))
  return canonicalFromTypedUnitField(typed, origin, tread)
}
