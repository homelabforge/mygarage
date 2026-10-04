import { describe, expect, it } from 'vitest'

import {
  costDecimals,
  displayDecimals,
  supplyDisplayUnit,
  toCanonical,
  toDisplay,
  unitCostToDisplay,
  type SupplyUnit,
  type SupplyVolumeUnit,
} from '../supplyUnits'

const FACTORS: [SupplyVolumeUnit, number][] = [
  ['mL', 0.001], ['L', 1],
  ['fl_oz_us', 0.0295735295625], ['fl_oz_uk', 0.0284130625],
  ['qt_us', 0.946352946], ['qt_uk', 1.1365225],
  ['gal_us', 3.785411784], ['gal_uk', 4.54609],
]
it.each(FACTORS)('%s uses the exact factor and round-trips', (unit, litres) => {
  expect(toCanonical(1, unit)).toBeCloseTo(litres, 12)
  expect(toDisplay(litres, unit)).toBeCloseTo(1, 12)
  expect(toDisplay(toCanonical(12.34, unit), unit)).toBeCloseTo(12.34, 9)
})

it('12 fl oz survives Numeric(12,3) storage as 12.00', () => {
  const stored = Math.round(toCanonical(12, 'fl_oz_us') * 1000) / 1000  // 0.355, the column's rounding
  expect(toDisplay(stored, 'fl_oz_us').toFixed(2)).toBe('12.00')
})

describe('supplyDisplayUnit', () => {
  it('count wins, a stored token wins, NULL falls back by system', () => {
    expect(supplyDisplayUnit({ unit_type: 'count', volume_unit: null }, 'imperial')).toBe('count')
    expect(supplyDisplayUnit({ unit_type: 'volume', volume_unit: 'fl_oz_uk' }, 'metric')).toBe('fl_oz_uk')
    expect(supplyDisplayUnit({ unit_type: 'volume', volume_unit: null }, 'imperial')).toBe('qt_us')
    expect(supplyDisplayUnit({ unit_type: 'volume', volume_unit: null }, 'metric')).toBe('L')
  })
  it('an unknown token reads as legacy, matching the backend lenient read', () => {
    const stale = { unit_type: 'volume' as const, volume_unit: 'pt_us' as SupplyVolumeUnit }
    expect(supplyDisplayUnit(stale, 'metric')).toBe('L')
  })
})

it('unitCostToDisplay prices the display unit', () => {
  expect(unitCostToDisplay('9.00', 'qt_us')).toBeCloseTo(8.517176514, 9)
  expect(unitCostToDisplay('9.00', 'count')).toBe(9)
  expect(unitCostToDisplay(null, 'L')).toBeNull()
})

it.each([
  ['mL', 0], ['count', 0],
  ['L', 2], ['fl_oz_us', 2], ['fl_oz_uk', 2], ['qt_us', 2], ['qt_uk', 2], ['gal_us', 2], ['gal_uk', 2],
] as [SupplyUnit, number][])('displayDecimals(%s) is %i', (unit, digits) => {
  expect(displayDecimals(unit)).toBe(digits)
})

it.each([
  ['mL', 4],
  ['L', 2], ['count', 2], ['fl_oz_us', 2], ['fl_oz_uk', 2], ['qt_us', 2], ['qt_uk', 2], ['gal_us', 2], ['gal_uk', 2],
] as [SupplyUnit, number][])('costDecimals(%s) is %i', (unit, digits) => {
  expect(costDecimals(unit)).toBe(digits)
})
