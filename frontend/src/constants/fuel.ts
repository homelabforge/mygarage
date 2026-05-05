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
