/**
 * The tie between `UnitConverter`'s token->factor maps and the adapter table.
 *
 * `utils/unitAdapters.ts` imports `UnitConverter`, so `utils/units.ts` cannot
 * import `adapterFor` back: the adapter table is built at module scope from
 * `UnitConverter.US_GALLONS_TO_LITERS`, and a runtime cycle would evaluate that
 * table while the class binding is still in its temporal dead zone. So
 * `units.ts` dispatches the volume and mass tokens itself, through
 * `LITERS_PER_VOLUME_UNIT` / `KG_PER_MASS_UNIT`.
 *
 * That is a second dispatch of the same decision, and the workstream's whole
 * subject is what happens when two copies drift (`decimalSafe.ts` held a
 * hardcoded US gallon under a comment claiming it mirrored `UnitConverter`,
 * which is defect L1). Two guards keep it honest:
 *
 * - the maps are `Record<UnitSet['volume'], number>` / `Record<UnitSet['mass'],
 *   number>`, so a token added to the API schema stops the build rather than
 *   silently falling through;
 * - this file, which asserts every entry equals what `UNIT_ADAPTERS` converts.
 *
 * Same shape as the backend's twice-derived preset tables, tied by a test.
 */

import { describe, expect, it } from 'vitest'
import { makeUnitSet } from '@/__tests__/factories'
import type { UnitSet } from '@/types/units'
import { adapterFor } from '../unitAdapters'
import { UnitConverter } from '../units'

const VOLUME_TOKENS: readonly UnitSet['volume'][] = ['L', 'gal_us', 'gal_uk']
const MASS_TOKENS: readonly UnitSet['mass'][] = ['kg', 'lb']

describe('UnitConverter token maps agree with the adapter table', () => {
  it('every volume token converts one typed unit to the same number of litres', () => {
    for (const volume of VOLUME_TOKENS) {
      const viaAdapter = adapterFor(makeUnitSet({ volume }), 'volume').toCanonical(1)
      expect(UnitConverter.LITERS_PER_VOLUME_UNIT[volume], volume).toBe(viaAdapter)
    }
  })

  it('every mass token converts one typed unit to the same number of kilograms', () => {
    for (const mass of MASS_TOKENS) {
      const viaAdapter = adapterFor(makeUnitSet({ mass }), 'mass').toCanonical(1)
      expect(UnitConverter.KG_PER_MASS_UNIT[mass], mass).toBe(viaAdapter)
    }
  })

  it('holds the exact published factors, so a silent edit to either side fails', () => {
    // Hand-written from the definitions, not read back from either table:
    // 1 US gallon = 3.78541 L, 1 imperial gallon = 4.54609 L, 1 lb = 0.453592 kg.
    expect(UnitConverter.LITERS_PER_VOLUME_UNIT).toEqual({
      L: 1,
      gal_us: 3.78541,
      gal_uk: 4.54609,
    })
    expect(UnitConverter.KG_PER_MASS_UNIT).toEqual({ kg: 1, lb: 0.453592 })
  })

  it('names every token the schema admits, so a new one cannot be forgotten', () => {
    // A token added to `UnitSet` without an entry breaks the Record type at
    // compile time; this catches the reverse mistake of adding the entry and
    // forgetting to widen the lists this file iterates.
    expect(Object.keys(UnitConverter.LITERS_PER_VOLUME_UNIT).sort()).toEqual(
      [...VOLUME_TOKENS].sort()
    )
    expect(Object.keys(UnitConverter.KG_PER_MASS_UNIT).sort()).toEqual([...MASS_TOKENS].sort())
  })
})
