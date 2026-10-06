import type { Supply } from '@/types/supplies'

import { RATE_DIGITS } from './formatUtils'
import { UnitConverter, type UnitSystem } from './units'

export type SupplyUnitType = 'volume' | 'count'
export type SupplyVolumeUnit = NonNullable<Supply['volume_unit']>
export type SupplyUnit = SupplyVolumeUnit | 'count'

// A const tuple so the form's z.enum can consume it.
export const SUPPLY_VOLUME_UNITS = [
  'mL',
  'L',
  'fl_oz_us',
  'fl_oz_uk',
  'qt_us',
  'qt_uk',
  'gal_us',
  'gal_uk',
] as const satisfies readonly SupplyVolumeUnit[]

const GAL_US = UnitConverter.LITERS_PER_VOLUME_UNIT.gal_us
const GAL_UK = UnitConverter.LITERS_PER_VOLUME_UNIT.gal_uk

// Litres per unit, all derived from the two gallons so the constants live in one place.
const LITERS_PER_SUPPLY_UNIT: Readonly<Record<SupplyVolumeUnit, number>> = {
  mL: 0.001,
  L: 1,
  fl_oz_us: GAL_US / 128,
  fl_oz_uk: GAL_UK / 160,
  qt_us: GAL_US / 4,
  qt_uk: GAL_UK / 4,
  gal_us: GAL_US,
  gal_uk: GAL_UK,
}

const UNIT_LABELS: Readonly<Record<SupplyUnit, string>> = {
  count: '',
  mL: 'mL',
  L: 'L',
  fl_oz_us: 'fl oz',
  fl_oz_uk: 'fl oz',
  qt_us: 'qt',
  qt_uk: 'qt',
  gal_us: 'gal',
  gal_uk: 'gal',
}

/**
 * The unit a supply is shown in: count wins, then the stored token, then (for
 * rows with no token yet) the old qt/L guess by unit preference. An unknown
 * token reads as legacy too, same as the backend's lenient read. Spec D8
 * amendment (Task B11) covers why this is the one place that still sees `system`.
 */
// units-exempt(binary-conversion): R3's survivor, at the DECLARATION. A NULL `volume_unit` has nothing resolved to read until the stored token exists, so the legacy qt/L choice follows `system`. Owner: deferred, pending the stored token on every row.
export function supplyDisplayUnit(
  supply: Pick<Supply, 'unit_type' | 'volume_unit'>,
  system: UnitSystem,
): SupplyUnit {
  if (supply.unit_type === 'count') return 'count'
  if (supply.volume_unit != null && Object.hasOwn(LITERS_PER_SUPPLY_UNIT, supply.volume_unit)) {
    return supply.volume_unit
  }
  // units-exempt(compare): R3 legacy branch; a row with no (or an unknown) token has no resolved unit to read, so qt/L follows `system`. Owner: deferred, pending the stored token on every row.
  return system === 'imperial' ? 'qt_us' : 'L'
}

/** Canonical (litres, or a count) to the given display unit. */
export function toDisplay(canonical: number, unit: SupplyUnit): number {
  if (unit === 'count') return canonical
  return canonical / LITERS_PER_SUPPLY_UNIT[unit]
}

/**
 * Display value back to canonical. Each entry field converts with the same
 * resolved unit its label shows, so a round trip is exact.
 */
export function toCanonical(display: number, unit: SupplyUnit): number {
  if (unit === 'count') return display
  return display * LITERS_PER_SUPPLY_UNIT[unit]
}

/** Short label for the unit; empty for count. */
export function unitLabel(unit: SupplyUnit): string {
  return UNIT_LABELS[unit]
}

/** Average unit cost per display unit; the API prices one canonical unit (a litre). */
export function unitCostToDisplay(
  costPerCanonical: string | number | null | undefined,
  unit: SupplyUnit,
): number | null {
  if (costPerCanonical == null) return null
  return Number(costPerCanonical) * toCanonical(1, unit)
}

/** Decimals worth showing: whole mL and counts, two for everything else. */
export function displayDecimals(unit: SupplyUnit): number {
  return unit === 'mL' || unit === 'count' ? 0 : 2
}

// Storage holds 0.001 L, which is 0.0003 gal at worst, so four decimals always show it.
const MAX_AMOUNT_DECIMALS = 4

/**
 * A canonical amount as text in the unit, in the picked language. A volume that
 * would round to zero at the unit's decimals gets more, so 3 mL reads 0.003 L.
 * Counts stay whole.
 */
export function formatSupplyAmount(canonical: number, unit: SupplyUnit, locale: string): string {
  const value = toDisplay(canonical, unit)
  let decimals = displayDecimals(unit)
  while (unit !== 'count' && decimals < MAX_AMOUNT_DECIMALS && value !== 0 && Number(Math.abs(value).toFixed(decimals)) === 0) {
    decimals++
  }
  return value.toLocaleString(locale, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

/** formatSupplyAmount plus the unit label; a count has none. */
export function formatSupplyQuantity(canonical: number, unit: SupplyUnit, locale: string): string {
  const label = unitLabel(unit)
  const text = formatSupplyAmount(canonical, unit, locale)
  return label ? `${text} ${label}` : text
}

/** Fraction digits for a unit cost. A mL costs fractions of a cent, so it gets four. */
export function costDecimals(unit: SupplyUnit): number {
  return unit === 'mL' ? 4 : RATE_DIGITS
}
