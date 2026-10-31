import { describe, expect, it } from 'vitest'

import {
  costDecimals,
  displayDecimals,
  formatSupplyAmount,
  formatSupplyQuantity,
  supplyDisplayUnit,
  toCanonical,
  toDisplay,
  unitCostToDisplay,
  unitLabel,
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

// A conversion guard, not a storage test: it rounds to 13 places by hand, so a
// column at the wrong scale can't fail it. The backend integration tests check
// what the database really keeps (at the old 3 places, 1 fl oz read back 1.01).
it.each([1, 1.03, 12])('%s fl oz still reads back after rounding litres to 13 places', (typed) => {
  const rounded = Number(toCanonical(typed, 'fl_oz_us').toFixed(13))
  expect(toDisplay(rounded, 'fl_oz_us').toFixed(2)).toBe(typed.toFixed(2))
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

describe('formatSupplyAmount', () => {
  it('uses the unit decimals for an ordinary amount', () => {
    expect(formatSupplyAmount(4.5, 'L', 'en-US')).toBe('4.50')
    expect(formatSupplyAmount(0.25, 'mL', 'en-US')).toBe('250')
    expect(formatSupplyAmount(4, 'count', 'en-US')).toBe('4')
  })

  // The smallest entry the API takes is 0.001 L; at two decimals every unit but mL reads it as 0.00.
  it.each([
    [0.003, 'L', '0.003'],
    [0.001, 'qt_us', '0.001'],
    [0.001, 'gal_us', '0.0003'],
    [0.001, 'gal_uk', '0.0002'],
    [-0.003, 'L', '-0.003'],
  ] as [number, SupplyUnit, string][])('%f L in %s reads %s, not zero', (litres, unit, text) => {
    expect(formatSupplyAmount(litres, unit, 'en-US')).toBe(text)
  })

  it('a true zero stays at the unit decimals, and a count stays whole', () => {
    expect(formatSupplyAmount(0, 'L', 'en-US')).toBe('0.00')
    expect(formatSupplyAmount(-0, 'L', 'en-US')).toBe('0.00')
    expect(formatSupplyAmount(0.4, 'count', 'en-US')).toBe('0')
    // Halves round away from zero both ways (Math.round used to give -2).
    expect(formatSupplyAmount(-2.5, 'count', 'en-US')).toBe('-3')
  })

  it('never goes past four decimals', () => {
    // Four is the cap: gallons need it for 0.001 L, and nothing needs more.
    expect(formatSupplyAmount(1e-9, 'L', 'en-US')).toBe('0.0000')
  })

  it('follows the locale, separators and grouping included', () => {
    expect(formatSupplyAmount(4.5, 'L', 'de-DE')).toBe('4,50')
    expect(formatSupplyAmount(0.003, 'L', 'de-DE')).toBe('0,003')
    expect(formatSupplyAmount(3.5, 'mL', 'en-US')).toBe('3,500')
  })
})

it('formatSupplyQuantity adds the label, and none for count', () => {
  expect(formatSupplyQuantity(0.003, 'L', 'en-US')).toBe('0.003 L')
  expect(formatSupplyQuantity(4, 'count', 'en-US')).toBe('4')
})

// D3: the UK supply units say so. The US and metric ones keep their labels.
it.each([
  ['qt_uk', 'qt (UK)'], ['fl_oz_uk', 'fl oz (UK)'], ['gal_uk', 'gal (UK)'],
] as [SupplyUnit, string][])('unitLabel(%s) is %s', (unit, label) => {
  expect(unitLabel(unit)).toBe(label)
})

it.each([
  ['qt_us', 'qt'], ['fl_oz_us', 'fl oz'], ['gal_us', 'gal'], ['L', 'L'], ['mL', 'mL'], ['count', ''],
] as [SupplyUnit, string][])('unitLabel(%s) stays %s (guard)', (unit, label) => {
  expect(unitLabel(unit)).toBe(label)
})

it('formatSupplyQuantity names a UK quart', () => {
  // 1.1365225 L is one UK quart.
  expect(formatSupplyQuantity(1.1365225, 'qt_uk', 'en-US')).toBe('1.00 qt (UK)')
})
