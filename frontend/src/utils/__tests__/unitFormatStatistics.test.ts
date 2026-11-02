/**
 * The single-unit helpers behind the Advanced statistics block. Inputs are the
 * canonical metric figures the API sends (per km, per litre); expectations are
 * worked by hand from the conversion factors.
 *
 * 1 mi = 1.609344 km, 1 US gal = 3.785411784 L.
 */
import { afterEach, describe, it, expect } from 'vitest'
import { setActiveLocale } from '@/constants/i18n'
import {
  formatCostPerSingleDistanceUnit,
  formatDistancePerCurrencyUnit,
  formatPricePerVolumeUnit,
  formatVolumeWithUnit,
  singleDistanceUnitLabel,
  singleVolumeUnitLabel,
} from '../unitFormat'
import { presetUnitsFor, type UnitSet } from '@/types/units'

const IMPERIAL = presetUnitsFor('imperial', 'us')
const METRIC = presetUnitsFor('metric', 'us')
/** Litres but miles - a set no binary metric/imperial switch can express. */
const LITRES_MILES: UnitSet = { ...METRIC, distance: 'mi' }

describe('single-unit labels', () => {
  it('follow the distance and volume tokens independently', () => {
    expect(singleDistanceUnitLabel(IMPERIAL)).toBe('mi')
    expect(singleDistanceUnitLabel(METRIC)).toBe('km')
    expect(singleVolumeUnitLabel(IMPERIAL)).toBe('gal')
    expect(singleVolumeUnitLabel(METRIC)).toBe('L')
    expect(singleDistanceUnitLabel(LITRES_MILES)).toBe('mi')
    expect(singleVolumeUnitLabel(LITRES_MILES)).toBe('L')
  })
})

describe('formatCostPerSingleDistanceUnit', () => {
  it('converts a per-km rate to per-mile', () => {
    // $0.10/km x 1.609344 km/mi = $0.161/mi
    expect(formatCostPerSingleDistanceUnit(IMPERIAL, 0.1, 'USD', 'en-US')).toContain('0.161')
  })
  it('leaves a per-km rate alone for kilometres', () => {
    expect(formatCostPerSingleDistanceUnit(METRIC, 0.1, 'USD', 'en-US')).toContain('0.100')
  })
})

describe('formatPricePerVolumeUnit', () => {
  it('converts a per-litre price to per-gallon', () => {
    // $1.00/L x 3.785411784 L/gal = $3.785/gal
    expect(formatPricePerVolumeUnit(IMPERIAL, 1, 'USD', 'en-US')).toContain('3.785')
  })
  it('keeps a per-litre price for litres', () => {
    expect(formatPricePerVolumeUnit(METRIC, 1.125, 'USD', 'en-US')).toContain('1.125')
  })
})

describe('formatVolumeWithUnit', () => {
  it('converts litres and appends the unit', () => {
    // 3.785411784 L is exactly one US gallon
    expect(formatVolumeWithUnit(IMPERIAL, 3.785411784)).toBe('1.00 gal')
    expect(formatVolumeWithUnit(METRIC, 115, 1)).toBe('115.0 L')
  })
  it('shows N/A for a missing value', () => {
    expect(formatVolumeWithUnit(METRIC, null)).toBe('N/A')
  })
})

describe('formatDistancePerCurrencyUnit', () => {
  it('converts km per currency unit to miles per currency unit', () => {
    // 16.09344 km per $ is 10 mi per $
    expect(formatDistancePerCurrencyUnit(IMPERIAL, 16.09344)).toBe('10.000')
    expect(formatDistancePerCurrencyUnit(METRIC, 12.5)).toBe('12.500')
  })
})


describe('locale-aware numbers', () => {
  afterEach(() => setActiveLocale('en'))

  it('writes the decimal comma and the grouping of the active locale', () => {
    setActiveLocale('de')
    // 40.7 L is 10.75 gal; German writes the decimal comma
    expect(formatVolumeWithUnit(IMPERIAL, 40.7, 2)).toBe('10,75 gal')
    // 1,234.5 km per currency unit is 767.083 mi (1234.5 / 1.609344)
    expect(formatDistancePerCurrencyUnit(IMPERIAL, 1234.5)).toBe('767,083')
    // large volumes group with the locale's separator
    expect(formatVolumeWithUnit(METRIC, 12345.6, 1)).toBe('12.345,6 L')
  })

  it('keeps the English form in an English locale', () => {
    setActiveLocale('en')
    expect(formatVolumeWithUnit(IMPERIAL, 40.7, 2)).toBe('10.75 gal')
    expect(formatVolumeWithUnit(METRIC, 12345.6, 1)).toBe('12,345.6 L')
  })
})
