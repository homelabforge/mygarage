/**
 * The summary-card and list helpers that render a volume, or something derived
 * from one.
 *
 * Defect L1's second half lived here: `formatCostPerVolume` multiplied by a
 * hardcoded `3.78541` and `formatVolumePerDistance` divided by it, so a UK
 * user's Avg Cost/gal card read about 20 percent low while the row beneath it,
 * which went through `priceToDisplay`, read the same wrong number. Fixing only
 * `decimalSafe` would have made the two disagree on one page, which is worse
 * than being uniformly wrong.
 *
 * Every gallon case pins the INSTANCE standard to `us` first: these helpers now
 * take the client's resolved `UnitSet`, and one still reading
 * `UnitConverter.getGallonStandard()` cannot pass a `gal_uk` case.
 */

import { beforeEach, describe, expect, it } from 'vitest'
import { makeUnitSet } from '@/__tests__/factories'
import { UnitConverter, UnitFormatter } from '../units'

const METRIC = makeUnitSet()
const US = makeUnitSet({ volume: 'gal_us', secondary_gallon: 'us' })
const UK = makeUnitSet({ volume: 'gal_uk', secondary_gallon: 'uk' })

beforeEach(() => {
  UnitConverter.setGallonStandard('us')
})

// All summary card helpers take CANONICAL METRIC inputs:
// - formatVolumeTotal: liters
// - formatCostPerVolume: $/L
describe('UnitConverter.litersToVolumeUnit', () => {
  it('hands a litre set its stored value untouched and rounds a gallon one for display', () => {
    // Form fields are seeded from this. A litre set must NOT go through
    // `roundResult`: re-rounding a canonical value the user never edited would
    // rewrite it on save, which is the round-trip corruption the tread work
    // spent a whole task on.
    expect(UnitConverter.litersToVolumeUnit(45.461, METRIC)).toBe(45.461)
    // 45.461 / 4.54609 = 10 exactly; / 3.78541 = 12.01.
    expect(UnitConverter.litersToVolumeUnit(45.461, UK)).toBe(10)
    expect(UnitConverter.litersToVolumeUnit(45.461, US)).toBe(12.01)
    expect(UnitConverter.litersToVolumeUnit(null, UK)).toBeNull()
    expect(UnitConverter.litersToVolumeUnit(undefined, METRIC)).toBeNull()
  })
})

describe('UnitFormatter summary card helpers', () => {
  describe('formatVolume', () => {
    it('renders in the resolved volume unit, not the instance gallon standard', () => {
      // 47.317625 L is 12.50 US gallons and 10.41 imperial ones.
      expect(UnitFormatter.formatVolume(47.317625, METRIC)).toBe('47.32 L')
      expect(UnitFormatter.formatVolume(47.317625, US)).toBe('12.50 gal')
      expect(UnitFormatter.formatVolume(47.317625, UK)).toBe('10.41 gal')
    })

    it('pairs a litre primary with the set\'s secondary gallon (D4b), not the global', () => {
      const metricUk = makeUnitSet({ secondary_gallon: 'uk' })
      expect(UnitFormatter.formatVolume(47.317625, METRIC, true)).toBe('47.32 L (12.50 gal)')
      expect(UnitFormatter.formatVolume(47.317625, metricUk, true)).toBe('47.32 L (10.41 gal)')
      expect(UnitFormatter.formatVolume(47.317625, UK, true)).toBe('10.41 gal (47.32 L)')
    })

    it('renders N/A for an absent value in every set', () => {
      expect(UnitFormatter.formatVolume(null, UK)).toBe('N/A')
      expect(UnitFormatter.formatVolume(undefined, UK)).toBe('N/A')
      // Not N/A, and not the US answer: the guard precedes the conversion.
      expect(UnitFormatter.formatVolume(45.4609, UK)).toBe('10.00 gal')
    })
  })

  describe('getVolumeUnit', () => {
    it('labels from the resolved volume token', () => {
      expect(UnitFormatter.getVolumeUnit(METRIC)).toBe('L')
      expect(UnitFormatter.getVolumeUnit(US)).toBe('gal')
      expect(UnitFormatter.getVolumeUnit(UK)).toBe('gal')
    })
  })

  describe('formatVolumeShort / formatVolumeTotal', () => {
    it('converts the total on the resolved token, at one decimal', () => {
      expect(UnitFormatter.formatVolumeShort(47.3, METRIC)).toBe('47.3 L')
      expect(UnitFormatter.formatVolumeShort(47.317625, US)).toBe('12.5 gal')
      // 47.317625 / 4.54609 = 10.408 -> 10.4
      expect(UnitFormatter.formatVolumeShort(47.317625, UK)).toBe('10.4 gal')
    })

    // ★ `formatVolumeTotal` WAS COVERED HERE, with a case named 'appends
    // "total" without changing the number'. That name states the defect: the
    // word it appended was English, in a method with no `t()`, rendering in two
    // summary cards. Fix round 1 retired it; the number half is
    // `formatVolumeShort` above and the word is a translated `volumeTotal` key
    // at each call site, asserted through the rendering tests in
    // FuelRecordList.test.tsx and DEFRecordList.test.tsx.
  })

  describe('formatCostPerVolume', () => {
    it('scales $/L by the resolved set\'s litres-per-unit', () => {
      expect(UnitFormatter.formatCostPerVolume(1.0, METRIC)).toBe('$1.00')
      // $1/L x 3.78541 = $3.79/gal; x 4.54609 = $4.55/gal. The card and the
      // row below it now agree, because both read the same resolved token.
      expect(UnitFormatter.formatCostPerVolume(1.0, US)).toBe('$3.79')
      expect(UnitFormatter.formatCostPerVolume(1.0, UK)).toBe('$4.55')
    })
  })

  // ★ `getCostPerVolumeLabel` WAS COVERED HERE too, and went the same way and
  // for the same reason: it glued the English words "Avg Cost/" to
  // `getVolumeUnit`, with no `t()`, in four summary cards. The unit half it
  // composed is `getVolumeUnit`, pinned above; the prose half is an
  // `avgCostPerVolume` key in all seven bundles, asserted where it renders.

  // ★ `formatCostPerDistance` and `getCostPerDistanceLabel` WERE COVERED HERE,
  // with cases named "metric: shows $/100 km" and "imperial: Cost/1k Miles".
  // Those described what the code did and pinned the defect: the binary system
  // is collapsed from VOLUME, so a `{volume:'L', distance:'mi'}` account read
  // "$10.00" under a "Cost/100 km" caption beside a miles odometer. Plan 3b
  // task 7 moved both functions to `utils/unitFormat.ts`, where `adapterFor`
  // supplies the distance half from the resolved set, and their cases moved
  // with them into `utils/__tests__/unitFormat.test.ts`, including the two
  // mixed sets the retired pair could not express and the denominators, which
  // did not change.

  // ★ `formatVolumePerDistance` and `getVolumePerDistanceLabel` WERE COVERED
  // HERE, with a case named "keeps the DISTANCE half on the binary system the
  // volume token collapses to". That was an honest description of what the code
  // did and it pinned the defect: a `{volume:'L', distance:'mi'}` account read
  // '4.7' under an 'L/1,000 km' label. Plan 3b task 6 moved both functions to
  // `utils/unitFormat.ts`, where `adapterFor` supplies BOTH halves from the
  // resolved set, and their cases moved with them into
  // `utils/__tests__/unitFormat.test.ts`, including the two mixed sets, which
  // the retired pair could not express at all.
})
