export type SupplyUnitType = 'volume' | 'count'
export type UnitSystem = 'metric' | 'imperial'

const L_PER_QUART = 0.946352946

/** Convert a canonical value (L for volume, count for count) to the user's display unit. */
export function canonicalToDisplay(
  value: number,
  unitType: SupplyUnitType,
  system: UnitSystem,
): number {
  if (unitType === 'count' || system === 'metric') return value
  return value / L_PER_QUART // liters → quarts
}

/** Convert a user-entered display value back to canonical (L / count). */
export function displayToCanonical(
  value: number,
  unitType: SupplyUnitType,
  system: UnitSystem,
): number {
  if (unitType === 'count' || system === 'metric') return value
  return value * L_PER_QUART // quarts → liters
}

/** Unit label for display. */
export function supplyUnitLabel(unitType: SupplyUnitType, system: UnitSystem): string {
  if (unitType === 'count') return ''
  return system === 'imperial' ? 'qt' : 'L'
}
