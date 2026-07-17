import { describe, expect, it } from 'vitest'

import { canonicalToDisplay, displayToCanonical, supplyUnitLabel } from '../supplyUnits'

describe('supplyUnits', () => {
  it('round-trips liters↔quarts for imperial volume', () => {
    const qt = canonicalToDisplay(1, 'volume', 'imperial')
    expect(qt).toBeCloseTo(1.05669, 4)
    expect(displayToCanonical(qt, 'volume', 'imperial')).toBeCloseTo(1, 6)
  })

  it('is identity for metric volume and for count', () => {
    expect(canonicalToDisplay(2, 'volume', 'metric')).toBe(2)
    expect(canonicalToDisplay(3, 'count', 'imperial')).toBe(3)
  })

  it('displayToCanonical is identity for metric volume and for count', () => {
    expect(displayToCanonical(2, 'volume', 'metric')).toBe(2)
    expect(displayToCanonical(3, 'count', 'imperial')).toBe(3)
  })

  describe('supplyUnitLabel', () => {
    it('returns qt for imperial volume', () => {
      expect(supplyUnitLabel('volume', 'imperial')).toBe('qt')
    })

    it('returns L for metric volume', () => {
      expect(supplyUnitLabel('volume', 'metric')).toBe('L')
    })

    it('returns empty string for count regardless of system', () => {
      expect(supplyUnitLabel('count', 'imperial')).toBe('')
      expect(supplyUnitLabel('count', 'metric')).toBe('')
    })
  })
})
