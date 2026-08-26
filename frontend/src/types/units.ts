/**
 * Unit preference types, re-exported from the generated OpenAPI schema.
 *
 * Nothing here is hand-maintained. `AuthContext` used to declare its own
 * `unit_preference?: 'imperial' | 'metric'`, which the API freshness gate
 * cannot see: regenerating the schema passed while that union went stale, and
 * migration 093 can now write a third value it never admitted.
 */

import type { components } from './api.generated'

export type UnitSet = components['schemas']['UnitSet']
export type UnitPreference = components['schemas']['UserResponse']['unit_preference']

export type VolumeUnit = UnitSet['volume']

/**
 * Collapse a resolved volume unit to the binary system the older helpers expect.
 *
 * Spec D8: a `custom` user still has to give `supplyUnits` and every other
 * binary consumer a defined answer, and the resolved volume unit is what
 * supplies it. Any gallon is imperial; litres are metric.
 */
export function binarySystemFor(volume: VolumeUnit): 'metric' | 'imperial' {
  return volume === 'L' ? 'metric' : 'imperial'
}
