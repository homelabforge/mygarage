/**
 * The volume and price entry/storage boundary, driven by a resolved `UnitSet`.
 *
 * Defect L1: these helpers took a binary `UnitSystem` and multiplied by a
 * hardcoded `3.78541` under a comment claiming the factor was "mirrored from
 * UnitConverter", which stopped being true when the UK gallon shipped in
 * v3.1.0. A UK user entering 6.00/gal stored 6.00 / 3.78541 = 1.585/L instead
 * of 6.00 / 4.54609 = 1.320/L, 20.1 percent high, and the form read it back
 * through the same wrong factor so nothing on screen disagreed.
 *
 * Substituting the dynamic `UnitConverter.gallonsToLiters` would NOT have been
 * the fix: its flavour came from the instance-wide gallon setting (which phase
 * 4 task 5 retired, leaving these statics writable only from a test), while
 * phase 1 gave each account its own
 * `resolved_units`. Every test below that names a gallon therefore pins the
 * INSTANCE standard to `us` first, so a helper still reading the global cannot
 * pass a `gal_uk` case.
 *
 * ★ WHAT PLAN 3b TASK 7 CHANGED ABOUT THIS FILE. `toCanonicalLiters` and the
 * exported `priceToCanonical` are gone: each took the value a form field
 * currently held and converted it straight to canonical, which is right for an
 * EDITED field and is the entry-grid shift for an untouched one. Their
 * conversion arithmetic is unchanged and is asserted below through the paths
 * that now carry it, which is the point rather than a translation exercise: a
 * test that still called the deleted helper would be asserting arithmetic no
 * form runs.
 */

import { beforeEach, describe, expect, it } from 'vitest'
import { makeUnitSet } from '@/__tests__/factories'
import {
  canonicalFromPriceField,
  priceToDisplay,
  seedPriceField,
  toLitersWirePrecision,
  type PriceBasis,
  type PriceFieldOrigin,
} from '../decimalSafe'
import { canonicalFromUnitField, makeUnitFormat, type UnitFieldOrigin } from '../unitFormat'
import { UnitConverter } from '../units'
import type { UnitSet } from '@/types/units'

const METRIC = makeUnitSet()
const US = makeUnitSet({ volume: 'gal_us', mass: 'lb', secondary_gallon: 'us' })
/** A UK-gallon user. On this instance the global standard stays `us` below. */
const UK = makeUnitSet({ volume: 'gal_uk', mass: 'lb', secondary_gallon: 'uk' })

/** A field nobody has seeded: every entry into it is an edit. */
const UNSEEDED: UnitFieldOrigin = { canonical: null, display: '' }

/** The same, for a price field quoted under one basis. */
const unseededPrice = (basis: PriceBasis | string | null): PriceFieldOrigin => ({
  canonical: null,
  display: '',
  basis,
})

/**
 * What a form posts for a volume the user TYPED, spelled as the forms spell it.
 *
 * The three writers all compose these two calls in this order, so exercising
 * the composition is exercising what ships. `String(x ?? '')` is the forms'
 * own shape: an absent value takes `canonicalFromUnitField`'s blank path.
 */
const enteredVolume = (typed: number | null | undefined, units: UnitSet): number | null =>
  toLitersWirePrecision(
    canonicalFromUnitField(String(typed ?? ''), UNSEEDED, makeUnitFormat(units).volume)
  )

/** The same for a price the user typed, under a basis they did not change. */
const enteredPrice = (
  typed: number | null | undefined,
  units: UnitSet,
  basis: PriceBasis | string | null | undefined
): number | null =>
  canonicalFromPriceField(String(typed ?? ''), unseededPrice(basis ?? null), units, basis)

beforeEach(() => {
  // The instance-wide flavour, as the retired `useGallonStandardSync` would
  // have left it on a US-default install. Nothing here may consult it.
  UnitConverter.setGallonStandard('us')
})

describe('an entered volume, through the adapter and the wire precision', () => {
  it('converts on the resolved volume token, not the instance gallon standard', () => {
    // 10 x 3.78541 = 37.8541 -> 37.854 at the API contract's 3 decimal places.
    expect(enteredVolume(10, US)).toBe(37.854)
    // 10 x 4.54609 = 45.4609 -> 45.461. The instance standard is `us`, so a
    // path reading the global would answer 37.854 here.
    expect(enteredVolume(10, UK)).toBe(45.461)
    expect(UnitConverter.getGallonStandard()).toBe('us')
  })

  it('leaves a litre entry as it was typed, apart from the wire precision', () => {
    expect(enteredVolume(50, METRIC)).toBe(50)
    // `liters` and `propane_liters` declare `decimal_places=3` in the API
    // schema, and pydantic REJECTS a fourth. A metric user typing 47.3176 used
    // to post it verbatim and take a 422.
    expect(enteredVolume(47.3176, METRIC)).toBe(47.318)
  })

  it('returns null for an absent or unparseable entry, and a number for a real one', () => {
    expect(enteredVolume(null, UK)).toBeNull()
    expect(enteredVolume(undefined, METRIC)).toBeNull()
    expect(enteredVolume(NaN, UK)).toBeNull()
    expect(enteredVolume(0, UK)).toBe(0)
    expect(enteredVolume(1, UK)).toBe(4.546)
  })

  it('★ applies the wire precision to a value the adapter left at twelve digits', () => {
    // The half `toLitersWirePrecision` owns, isolated. 12.345 US gal is
    // 46.73088645 L, which the adapter answers unrounded and pydantic rejects.
    const u = makeUnitFormat(US)
    expect(u.volume.toCanonical(12.345)).toBe(46.73088645)
    expect(toLitersWirePrecision(u.volume.toCanonical(12.345))).toBe(46.731)
    expect(toLitersWirePrecision(null)).toBeNull()
    expect(toLitersWirePrecision(NaN)).toBeNull()
  })
})

// ★ Distance, mass and length used to be asserted here in their binary form,
// as `toCanonicalKm(100, 'metric')` and two siblings. Phase 3b task 5 DELETED
// all three under ruling R8: each took a `UnitSystem` collapsed from the
// user's VOLUME choice and wrote a canonical value off it, so a
// `{volume:'L', distance:'mi'}` user's 500 miles stored as 500 km. Those
// assertions are not moved or replaced here because there is nothing left in
// this file to assert them against; what replaced the helpers is
// `seedUnitField` / `canonicalFromUnitField` in `utils/unitFormat.ts`, tested
// beside it. That the three stay deleted is asserted structurally, in
// `utils/__tests__/unitsBinaryApiSurface.test.ts`, which also pins that no
// export here converts a display value straight to canonical any more.

describe('price display and entry — per_volume', () => {
  it('scales the canonical $/L by the resolved set\'s litres-per-unit', () => {
    // Real bug repro: stored $1.136/L reads $4.30/gal on US gallons and
    // $5.16/gal on imperial ones. 1.136 x 3.78541 = 4.30022576 -> 4.300;
    // 1.136 x 4.54609 = 5.16435824 -> 5.164.
    expect(priceToDisplay(1.136, US, 'per_volume')).toBe(4.3)
    expect(priceToDisplay(1.136, UK, 'per_volume')).toBe(5.164)
    // A litre user's price IS canonical: no conversion, and no re-rounding of
    // a stored value they never touched.
    expect(priceToDisplay(1.135845, METRIC, 'per_volume')).toBe(1.135845)
  })

  it('divides an entered price by the resolved set\'s litres-per-unit', () => {
    // 6.00/gal is 6 / 4.54609 = 1.31981548979 $/L for an imperial gallon and
    // 6 / 3.78541 = 1.58503306115 for a US one. The 20.1 percent that L1 was.
    expect(enteredPrice(6, UK, 'per_volume')).toBe(1.31981548979)
    expect(enteredPrice(6, US, 'per_volume')).toBe(1.58503306115)
    expect(enteredPrice(1.136, METRIC, 'per_volume')).toBe(1.136)
  })

  it('round-trips an entered UK price through canonical and back unchanged', () => {
    const typed = 6
    const canonical = enteredPrice(typed, UK, 'per_volume')
    expect(canonical).toBe(1.31981548979)
    expect(priceToDisplay(canonical, UK, 'per_volume')).toBe(typed)
  })

  it('accepts the string an API response carries', () => {
    expect(priceToDisplay('1.136', UK, 'per_volume')).toBe(5.164)
    expect(seedPriceField('1.136', UK, 'per_volume').canonical).toBe(1.136)
  })
})

describe('price display and entry — per_weight', () => {
  it('scales by the resolved MASS token, independently of the volume one', () => {
    // $2.2046/kg is about $1.00/lb; $1.00/lb is 1 / 0.453592 = 2.20462442018.
    expect(priceToDisplay(2.2046, UK, 'per_weight')).toBe(1)
    expect(enteredPrice(1, UK, 'per_weight')).toBe(2.20462442018)
    // A kilogram user's price is already canonical, even though the same set
    // names a gallon for volume.
    const kgWithGallons = makeUnitSet({ volume: 'gal_uk', mass: 'kg' })
    expect(priceToDisplay(2.2046, kgWithGallons, 'per_weight')).toBe(2.2046)
  })
})

describe('price display and entry — bases with no unit to convert', () => {
  it('leaves per_kwh, per_tank and an unknown basis alone on a gallon set', () => {
    expect(priceToDisplay(0.13, UK, 'per_kwh')).toBe(0.13)
    expect(enteredPrice(0.13, UK, 'per_kwh')).toBe(0.13)
    expect(priceToDisplay(25, UK, 'per_tank')).toBe(25)
    expect(enteredPrice(25, UK, 'per_tank')).toBe(25)
    expect(priceToDisplay(1.136, UK, null)).toBe(1.136)
    expect(priceToDisplay(1.136, UK, undefined)).toBe(1.136)
    expect(priceToDisplay(1.136, UK, 'something_else')).toBe(1.136)
    // Same set, same value, a basis that DOES name a unit: proves the four
    // pass-throughs above are the basis dispatch and not a dead helper.
    expect(priceToDisplay(1.136, UK, 'per_volume')).toBe(5.164)
  })

  it('returns null for an absent or unparseable price, and converts a real one', () => {
    expect(priceToDisplay(null, UK, 'per_volume')).toBeNull()
    expect(priceToDisplay(undefined, METRIC, 'per_volume')).toBeNull()
    expect(priceToDisplay('not a number', UK, 'per_volume')).toBeNull()
    expect(enteredPrice(NaN, UK, 'per_volume')).toBeNull()
    expect(enteredPrice(6, UK, 'per_volume')).toBe(1.31981548979)
  })
})

describe('seedPriceField / canonicalFromPriceField — the origin', () => {
  it('remembers the canonical price, the string it produced and the basis', () => {
    expect(seedPriceField(1.136, UK, 'per_volume')).toStrictEqual({
      canonical: 1.136,
      display: '5.164',
      basis: 'per_volume',
    })
  })

  it('seeds an absent price as an empty field with no canonical origin', () => {
    expect(seedPriceField(null, UK, 'per_volume')).toStrictEqual({
      canonical: null,
      display: '',
      basis: 'per_volume',
    })
    expect(seedPriceField(undefined, UK, null)).toStrictEqual({
      canonical: null,
      display: '',
      basis: null,
    })
  })

  it('★ returns the ORIGINAL canonical price when the field was not edited', () => {
    // The whole point, and the shape ruling R4 names. $1.136/L reads 5.164/gal
    // to a UK account, and 5.164/gal converts back to 1.13592119822 $/L, so a
    // form that reconverted an untouched field rewrote a price nobody edited.
    const origin = seedPriceField(1.136, UK, 'per_volume')
    expect(origin.display).toBe('5.164')
    expect(canonicalFromPriceField('5.164', origin, UK, 'per_volume')).toBe(1.136)
    // Stated rather than implied: the reconversion really does move, so the
    // assertion above is not satisfied by an arithmetic coincidence.
    expect(canonicalFromPriceField('5.164', unseededPrice('per_volume'), UK, 'per_volume')).toBe(
      1.13592119822
    )
  })

  it('converts once the number differs from what the field was seeded with', () => {
    const origin = seedPriceField(1.136, UK, 'per_volume')
    // 5.20 / 4.54609 = 1.14384009116 $/L
    expect(canonicalFromPriceField('5.2', origin, UK, 'per_volume')).toBe(1.14384009116)
  })

  it('reads a cleared price field as null, not as the value it used to hold', () => {
    const origin = seedPriceField(1.136, UK, 'per_volume')
    expect(canonicalFromPriceField('', origin, UK, 'per_volume')).toBeNull()
    expect(canonicalFromPriceField('   ', origin, UK, 'per_volume')).toBeNull()
  })

  it('accepts the control\'s own spelling of the seeded number as unchanged', () => {
    // `String(priceToDisplay(...))` writes '4.3'; a react-hook-form NUMBER
    // field round-trips through `Number` and can hand back '4.30'.
    const origin = seedPriceField(1.136, US, 'per_volume')
    expect(origin.display).toBe('4.3')
    expect(canonicalFromPriceField('4.30', origin, US, 'per_volume')).toBe(1.136)
  })

  it('★ treats a moved BASIS as an edit even when the number never changed', () => {
    // The leg a quantity origin has no place for. The fuel form's price_basis
    // is a <select>: switching per_volume -> per_weight leaves 4.3 in the box
    // and makes it $/lb. Handing back the stored $/L would relabel a gallon
    // price as a pound price.
    const origin = seedPriceField(1.136, US, 'per_volume')
    expect(origin.display).toBe('4.3')
    // 4.3 / 0.453592 = 9.47988500679 $/kg
    expect(canonicalFromPriceField('4.3', origin, US, 'per_weight')).toBe(9.47988500679)
    expect(canonicalFromPriceField('4.3', origin, US, 'per_weight')).not.toBe(1.136)
  })

  it('★ reinterprets a legacy per_tank seed as the per_volume price it is saved as', () => {
    // PropaneRecordForm's real shape: a pre-fix record stored the user's typed
    // $/gal under basis='per_tank', so the seed passes it through unconverted
    // and the submit re-reads it as per_volume. That reinterpretation is the
    // migration; an origin blind to the basis would defeat it and store 2.899
    // as a per-litre price.
    const origin = seedPriceField(2.899, US, 'per_tank')
    expect(origin.display).toBe('2.899')
    // 2.899 / 3.78541 = 0.765835140711 $/L
    expect(canonicalFromPriceField('2.899', origin, US, 'per_volume')).toBe(0.765835140711)
  })

  it('holds an unchanged basis and an unchanged number together', () => {
    // The negative control for the two cases above: with the basis steady, the
    // origin still wins, so neither of them is passing because the basis leg
    // fires unconditionally.
    const origin = seedPriceField(2.899, US, 'per_tank')
    expect(canonicalFromPriceField('2.899', origin, US, 'per_tank')).toBe(2.899)
  })
})
