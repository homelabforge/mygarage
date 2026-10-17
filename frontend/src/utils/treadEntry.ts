/**
 * A digital gauge's decimal inches typed into a /32 in tread field.
 *
 * Only an entry strictly between 0 and 1 is read as inches: no stick gauge
 * reads a fraction of a 32nd, and no car tire has an inch of tread. Zero, whole
 * 32nds and every millimetre entry stay as typed.
 */

import { canonicalFromUnitField, type QuantityFormat, type UnitFieldOrigin } from './unitFormat'
import { UnitConverter } from './units'

/** Canonical tread is millimetres; the inch factor is in metres. */
const MM_PER_M = 1000

/**
 * The 32nds a decimal-inch entry means, or null when the entry means itself.
 *
 * Rounded by the field's own formatter, so 0.346 lands on 11 the way any value does.
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
 * A tread field's canonical value, with a gauge's decimal inches read as a new measurement.
 *
 * A converted entry skips the origin. 8.40 mm seeds the field as 11 and 0.346 in
 * is 11 too, so going through the origin would keep the old 8.40 for a reading
 * the user just took. Anything else goes through `canonicalFromUnitField` as before.
 */
export function canonicalFromTreadField(
  typed: string,
  origin: UnitFieldOrigin,
  tread: QuantityFormat
): number | null {
  const thirtySeconds = thirtySecondsFromDecimalInches(typed, tread)
  if (thirtySeconds !== null) return tread.toCanonical(Number(thirtySeconds))
  return canonicalFromUnitField(typed, origin, tread)
}
