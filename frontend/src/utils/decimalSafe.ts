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

export type PriceBasis = 'per_volume' | 'per_weight' | 'per_kwh' | 'per_tank'

// Exact conversion factors mirrored from UnitConverter (kept private there).
// Price math needs 3-decimal precision to match DB Numeric(6,3); the existing
// volume/weight helpers round to 2 decimals, so we can't reuse them directly.
const LITERS_PER_GALLON = 3.78541
const KG_PER_LB = 0.453592

function roundPrice(n: number): number {
  return parseFloat(n.toFixed(3))
}

/**
 * Convert a canonical SI price (per liter / per kg) into the user's display
 * unit (per gallon / per lb for imperial). per_kwh and per_tank are universal
 * and pass through unchanged.
 */
export function priceToDisplay(
  value: number | string | null | undefined,
  system: UnitSystem,
  basis: PriceBasis | string | null | undefined,
): number | null {
  if (value == null) return null
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return null
  if (system === 'metric') return num
  if (basis === 'per_volume') return roundPrice(num * LITERS_PER_GALLON)
  if (basis === 'per_weight') return roundPrice(num * KG_PER_LB)
  return num
}

/**
 * Convert a user-entered display-unit price (per gallon / per lb for imperial)
 * back into canonical SI ($/L, $/kg). Inverse of priceToDisplay.
 */
export function priceToCanonical(
  value: number | null | undefined,
  system: UnitSystem,
  basis: PriceBasis | string | null | undefined,
): number | null {
  if (value == null || isNaN(value)) return null
  if (system === 'metric') return value
  if (basis === 'per_volume') return roundPrice(value / LITERS_PER_GALLON)
  if (basis === 'per_weight') return roundPrice(value / KG_PER_LB)
  return value
}
