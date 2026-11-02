/**
 * Fuel-tracking enum vocabularies — single source of truth for the frontend.
 *
 * Mirrors backend/app/constants/fuel.py. The values must stay in sync; the
 * backend Pydantic validators will reject any string outside these sets.
 */

export const PAYMENT_METHOD_VALUES = [
  'cash',
  'credit',
  'debit',
  'fleet_card',
  'app',
  'other',
] as const

export type PaymentMethod = (typeof PAYMENT_METHOD_VALUES)[number]

export const TRIP_TYPE_VALUES = [
  'private',
  'business',
  'commute',
  'other',
] as const

export type TripType = (typeof TRIP_TYPE_VALUES)[number]

export const FUEL_TYPE_VALUES = [
  'gasoline',
  'diesel',
  'electric',
  'hybrid',
  'plugin_hybrid',
  'e85',
  'propane_lpg',
  'cng',
  'hydrogen',
  'other',
] as const

export type FuelType = (typeof FUEL_TYPE_VALUES)[number]

/**
 * Human-readable labels for the FUEL_TYPE_VALUES set. Surfaced wherever
 * the user picks a fuel type (vehicle add/edit form, fuel record
 * fuel_type_used dropdown on multi-fuel vehicles). Mirrors backend
 * canonical enum values; localization-friendly callers should pull
 * from i18n translations and fall back here.
 */
export const FUEL_TYPE_LABELS: Record<FuelType, string> = {
  gasoline: 'Gasoline',
  diesel: 'Diesel',
  electric: 'Electric',
  hybrid: 'Hybrid',
  plugin_hybrid: 'Plug-in Hybrid',
  e85: 'E85 / Flex Fuel',
  propane_lpg: 'Propane / LPG',
  cng: 'CNG',
  hydrogen: 'Hydrogen',
  other: 'Other',
}

/**
 * True when a (possibly legacy/free-text) fuel_type value denotes diesel.
 * Canonical values are lowercase (e.g. "diesel"); `.includes()` keeps this
 * resilient to older free-text data without a separate migration. Shared by
 * every diesel-gated UI check (DEF tracking visibility/read-only state,
 * DEF tank capacity editability) so the matching rule only lives in one
 * place — mirrors the backend's diesel-only DEF gate (see
 * backend/app/constants/fuel.py).
 */
export function isDieselFuelType(fuelType?: string | null): boolean {
  return fuelType?.toLowerCase().includes('diesel') ?? false
}

export function isFuelType(value: string | null | undefined): value is FuelType {
  return !!value && (FUEL_TYPE_VALUES as readonly string[]).includes(value)
}

/**
 * EN 16942 pump labels (#211): the identifier in the circle (petrol), square
 * (diesel) or diamond (gaseous fuels) printed on every nozzle sold in the
 * EU since 2018. Mirrors `FuelGradeEnum` in backend/app/constants/fuel.py.
 */
export const FUEL_GRADE_VALUES = [
  'E5',
  'E10',
  'E85',
  'B7',
  'B10',
  'B20',
  'B30',
  'B100',
  'XTL',
  'H2',
  'CNG',
  'LPG',
  'LNG',
] as const

export type FuelGrade = (typeof FUEL_GRADE_VALUES)[number]

/**
 * Which labels a pump can carry for each fuel type. A fuel type that is
 * absent (electric, other) has no label. Mirrors `GRADES_FOR_FUEL_TYPE`.
 */
export const GRADES_FOR_FUEL_TYPE: Partial<Record<FuelType, readonly FuelGrade[]>> = {
  gasoline: ['E5', 'E10'],
  hybrid: ['E5', 'E10'],
  plugin_hybrid: ['E5', 'E10'],
  e85: ['E85'],
  diesel: ['B7', 'B10', 'B20', 'B30', 'B100', 'XTL'],
  propane_lpg: ['LPG'],
  cng: ['CNG', 'LNG'],
  hydrogen: ['H2'],
}

export function isFuelGrade(value: string | null | undefined): value is FuelGrade {
  return !!value && (FUEL_GRADE_VALUES as readonly string[]).includes(value)
}

/** The labels a fill-up of this fuel type can carry; empty when none applies. */
export function gradesForFuelType(fuelType: string | null | undefined): readonly FuelGrade[] {
  return isFuelType(fuelType) ? (GRADES_FOR_FUEL_TYPE[fuelType] ?? []) : []
}
