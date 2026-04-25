import { UnitConverter } from './units'
import type { UnitSystem } from './units'

/**
 * Convert a user-entered numeric value into its canonical metric form
 * suitable for submitting to the API. Returns the raw number for metric
 * users (no float drift), and converts once for imperial users.
 *
 * Use on form-submit ONLY. Display-time conversion uses UnitFormatter.
 */
export function toCanonicalKm(value: number | null | undefined, system: UnitSystem): number | null {
  if (value == null || isNaN(value)) return null
  return system === 'metric' ? value : (UnitConverter.milesToKm(value) ?? value)
}

export function toCanonicalLiters(value: number | null | undefined, system: UnitSystem): number | null {
  if (value == null || isNaN(value)) return null
  return system === 'metric' ? value : (UnitConverter.gallonsToLiters(value) ?? value)
}

export function toCanonicalKg(value: number | null | undefined, system: UnitSystem): number | null {
  if (value == null || isNaN(value)) return null
  return system === 'metric' ? value : (UnitConverter.lbsToKg(value) ?? value)
}

export function toCanonicalMeters(value: number | null | undefined, system: UnitSystem): number | null {
  if (value == null || isNaN(value)) return null
  return system === 'metric' ? value : (UnitConverter.feetToMeters(value) ?? value)
}
