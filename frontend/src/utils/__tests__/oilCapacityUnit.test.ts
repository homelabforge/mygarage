/**
 * Oil capacity is read in quarts wherever fuel is read in gallons.
 *
 * The field used the shared `volume` adapter, so a reader on `gal_us` was asked
 * for GALLONS of engine oil. Nobody expresses it that way, and the failure is
 * silent rather than ugly: entering "12" for a 6.7 Cummins stored
 * `12 x 3.785411784 = 45.42 L`, and the card read `12 gal` straight back. The
 * round trip is symmetric, so the UI cannot show the error; it surfaces only
 * when something else reads the canonical litres. Measured on a real instance,
 * two vehicles were stored 3.785x over.
 *
 * THE QUART IS DERIVED, NOT CONSTANTED
 * ------------------------------------
 * `utils/supplyUnits.ts` solves the same problem with a hardcoded
 * `L_PER_QUART = 0.946352946`, which is the US liquid quart, and its own
 * docstring records the resulting 20.1% defect for UK instances. It also
 * records the fix: `LITERS_PER_VOLUME_UNIT[gal_x] / 4`, derivable today with no
 * new vocabulary. That is what this does, so the UK case is right on day one
 * rather than deferred.
 */

import { describe, expect, it } from 'vitest'
import { presetUnitsFor, type UnitSet } from '@/types/units'
import { oilCapacityFormat } from '../oilCapacityUnit'

const US: UnitSet = presetUnitsFor('imperial', 'us')
const UK: UnitSet = presetUnitsFor('imperial', 'uk')
const METRIC: UnitSet = presetUnitsFor('metric', 'us')

describe('oilCapacityFormat', () => {
  it('reads quarts, not gallons, for a US reader', () => {
    const f = oilCapacityFormat(US)
    expect(f.label).toBe('qt')
    // 4.7 L is a real 6.7 Cummins-adjacent figure; in gallons it read 1.24.
    expect(f.toDisplay(4.7)).toBeCloseTo(4.967, 2)
  })

  it('uses the IMPERIAL quart for a UK reader, which supplies gets wrong', () => {
    // The defect supplyUnits.ts documents: one UK quart is 1.1365225 L, not the
    // US 0.946352946. Reading a UK entry with the US constant is 20.1% out.
    const f = oilCapacityFormat(UK)
    expect(f.label).toBe('qt')
    expect(f.toCanonical(1)).toBeCloseTo(1.1365225, 6)
    expect(f.toCanonical(1)).not.toBeCloseTo(0.946352946, 3)
  })

  it('leaves a metric reader in litres', () => {
    const f = oilCapacityFormat(METRIC)
    expect(f.label).toBe('L')
    expect(f.toDisplay(4.7)).toBeCloseTo(4.7, 6)
    expect(f.toCanonical(4.7)).toBeCloseTo(4.7, 6)
  })

  it('round-trips a US quart entry back to the same number', () => {
    const f = oilCapacityFormat(US)
    expect(f.toDisplay(f.toCanonical(12))).toBeCloseTo(12, 6)
  })

  it('stores the figure a Cummins owner means when they type 12', () => {
    // The bug, stated as the number it produced: 12 typed as gallons stored
    // 45.42 L. Typed as quarts it stores 11.36, which is the published
    // 12 US qt capacity.
    const f = oilCapacityFormat(US)
    expect(f.toCanonical(12)).toBeCloseTo(11.356, 2)
    expect(f.toCanonical(12)).not.toBeCloseTo(45.42, 1)
  })

  it('never renders oil capacity through the fuel adapter', () => {
    // Guard-the-guard: a regression that re-pointed this at `volume` would make
    // every assertion above pass for gallons if they only checked round trips.
    const f = oilCapacityFormat(US)
    const oneGallonInLitres = 3.785411784
    expect(f.toCanonical(1)).not.toBeCloseTo(oneGallonInLitres, 3)
  })
})
