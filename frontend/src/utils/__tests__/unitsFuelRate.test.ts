import { describe, it, expect } from 'vitest'
import { UnitFormatter } from '../units'

// Hours-tracking economy: formatFuelRate/getFuelRateUnit are the L/hr
// analog of formatFuelEconomy/getFuelEconomyUnit. Engine hours are
// dimensionless — only the volume side (L vs gal) converts between
// systems, using the EXACT US-gallon factor (1 gal = 3.785411784 L),
// distinct from UnitConverter's rounded US_GALLONS_TO_LITERS (3.78541).
describe('UnitFormatter.formatFuelRate', () => {
  it('metric: shows L/hr with 2 decimals', () => {
    expect(UnitFormatter.formatFuelRate(3.2, 'metric')).toBe('3.20 L/hr')
  })

  it('imperial: converts L/hr to GPH with 2 decimals (exact factor)', () => {
    // 3.785411784 L/hr / 3.785411784 = 1.00 GPH (gallons/hour) exactly
    expect(UnitFormatter.formatFuelRate(3.785411784, 'imperial')).toBe('1.00 GPH')
  })

  it('imperial: a realistic value converts and rounds correctly', () => {
    // 12 L/hr / 3.785411784 = 3.1701... -> 3.17 GPH
    expect(UnitFormatter.formatFuelRate(12, 'imperial')).toBe('3.17 GPH')
  })

  it('accepts a string value (wire format) — same defensive string-parsing as formatFuelEconomy', () => {
    // The Numeric param type is number|null|undefined (matches every other
    // formatX method in this file), but the API wire format sends Decimal
    // fields as strings, so the body defensively parses them too. Cast to
    // exercise that branch under the declared (narrower) type.
    expect(UnitFormatter.formatFuelRate('3.20' as unknown as number, 'metric')).toBe('3.20 L/hr')
  })

  it('metric showBoth includes the GPH conversion in parens', () => {
    expect(UnitFormatter.formatFuelRate(3.785411784, 'metric', true)).toBe('3.79 L/hr (1.00 GPH)')
  })

  it('imperial showBoth includes the L/hr value in parens', () => {
    expect(UnitFormatter.formatFuelRate(3.785411784, 'imperial', true)).toBe('1.00 GPH (3.79 L/hr)')
  })

  it('returns N/A for null', () => {
    expect(UnitFormatter.formatFuelRate(null, 'metric')).toBe('N/A')
  })

  it('returns N/A for undefined', () => {
    expect(UnitFormatter.formatFuelRate(undefined, 'imperial')).toBe('N/A')
  })

  it('returns N/A for zero (no computable rate, mirrors formatFuelEconomy)', () => {
    expect(UnitFormatter.formatFuelRate(0, 'metric')).toBe('N/A')
  })

  it('returns N/A for a non-numeric string', () => {
    expect(UnitFormatter.formatFuelRate('not-a-number' as unknown as number, 'metric')).toBe('N/A')
  })
})

describe('UnitFormatter.getFuelRateUnit', () => {
  it('imperial: GPH', () => {
    expect(UnitFormatter.getFuelRateUnit('imperial')).toBe('GPH')
  })

  it('metric: L/hr', () => {
    expect(UnitFormatter.getFuelRateUnit('metric')).toBe('L/hr')
  })
})
