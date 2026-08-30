/**
 * The UK-gallon corruption DETECTOR, and its four constraints.
 *
 * Defect L1 stored a per-volume price through a hardcoded US gallon while the
 * volume beside it went through the instance-wide (possibly UK) one. The two
 * factors then show up in one stored row, because both forms compute the total
 * in DISPLAY units: `cost = displayVolume x displayPrice`. So
 *
 *     price_per_unit x volume = gross_cost x (volumeFactor / priceFactor)
 *
 * and the ratio reads 1.0000 when the two factors agree and 4.54609 / 3.78541 =
 * 1.20095 when the price took the US gallon and the volume the imperial one.
 *
 * ★ It is a DETECTOR WITH A PRECONDITION, not an invariant, and calling it
 * self-detecting would be wrong. Four constraints, each of which turns a clean
 * row into a false positive (or a real one into a miss) when dropped:
 *
 *  1. `price_basis = 'per_volume'`. `per_tank`, `per_kwh` and `per_weight` are
 *     not a per-volume price at all, and their numbers are unrelated to the
 *     volume column.
 *  2. Volume is `COALESCE(liters, propane_liters)`. `PropaneRecordForm` writes
 *     `liters: undefined` deliberately and uses its own column, so a
 *     liters-only detector silently skips every propane row.
 *  3. Rebates are added back. Stored `cost` is NET of rebate, so 10 L at
 *     1.00/L with an 8.00 rebate stores `cost = 2` and the naive ratio reads
 *     5.0, flagging a perfectly clean row.
 *  4. The gross cost must RECONCILE to price x volume under one of the two
 *     hypotheses. `FuelRecordForm` deliberately preserves a stored total
 *     because a receipt may include a car wash, so cost, price and volume are
 *     allowed to be independent by design. A 10 L row at $1/L with a $12 total
 *     reads 0.833 and is not evidence either way; it must leave the population
 *     BEFORE the ratio is read.
 *
 * And a suspect verdict is a CANDIDATE, not proof: a preserved discounted total
 * can land on 1.20095 with no UK bug at all. Confirming one needs the
 * instance's gallon history, which is why no row on this instance was declared
 * corrupt from the ratio alone (`imperial_gallon_standard` is `us`, checked row
 * by row).
 */

import { describe, expect, it } from 'vitest'

/** The ratio a row with one factor on both sides reads. */
const CLEAN_RATIO = 1
/** 4.54609 / 3.78541: an imperial-gallon volume against a US-gallon price. */
const CORRUPT_RATIO = 1.20095
/** Relative slack for the 2-3 decimal places the columns are stored at. */
const TOLERANCE = 0.005

/** What one stored fuel or DEF row contributes to the audit. */
interface StoredRow {
  price_basis: string | null
  price_per_unit: number | null
  liters: number | null
  propane_liters: number | null
  cost: number | null
  rebate: number | null
}

type Verdict = 'clean' | 'suspect' | 'excluded'

/**
 * Classify one stored row.
 *
 * @param row The row as the database holds it, canonical units throughout.
 * @returns `clean`, `suspect`, or `excluded` when the row is not evidence.
 */
function classify(row: StoredRow): Verdict {
  // Constraint 1: only a per-volume price has a volume denominator.
  if (row.price_basis !== 'per_volume') return 'excluded'
  // Constraint 2: propane keeps its volume in its own column.
  const volume = row.liters ?? row.propane_liters
  if (volume === null || row.price_per_unit === null || row.cost === null) return 'excluded'
  // Constraint 3: stored cost is NET of any rebate.
  const gross = row.cost + (row.rebate ?? 0)
  if (gross === 0) return 'excluded'
  const ratio = (row.price_per_unit * volume) / gross
  // Constraint 4: a ratio that matches neither hypothesis means the total does
  // not reconcile to price x volume, so the row says nothing about the factors.
  if (Math.abs(ratio - CLEAN_RATIO) <= TOLERANCE) return 'clean'
  if (Math.abs(ratio - CORRUPT_RATIO) <= TOLERANCE * CORRUPT_RATIO) return 'suspect'
  return 'excluded'
}

/** A per-volume row with everything absent, for one-field fixtures. */
const EMPTY: StoredRow = {
  price_basis: 'per_volume',
  price_per_unit: null,
  liters: null,
  propane_liters: null,
  cost: null,
  rebate: null,
}

describe('the UK-gallon corruption detector', () => {
  it('reads 1.0000 on a row both of whose factors agree', () => {
    // 10 imperial gallons at 6.00/gal, stored the way this task now stores it:
    // liters = 10 x 4.54609 = 45.461, price = 6 / 4.54609 = 1.31981548979.
    expect(
      classify({ ...EMPTY, price_per_unit: 1.31981548979, liters: 45.461, cost: 60 })
    ).toBe('clean')
    // The same entry with US gallons on both sides is equally clean: the
    // detector finds a factor MISMATCH, not a particular flavour.
    expect(
      classify({ ...EMPTY, price_per_unit: 1.58503306115, liters: 37.854, cost: 60 })
    ).toBe('clean')
  })

  it('reads 1.20095 on a row whose price took the US gallon and volume the imperial one', () => {
    // Exactly what shipped: volume through the dynamic (UK) converter at two
    // decimals, price through decimalSafe's hardcoded 3.78541 at three.
    // 1.585 x 45.46 / 60 = 1.20090.
    expect(classify({ ...EMPTY, price_per_unit: 1.585, liters: 45.46, cost: 60 })).toBe('suspect')
  })

  it('CONSTRAINT 1: a non-per_volume basis leaves the population', () => {
    // Same numbers, so the ratio is still 1.20090; only the basis differs.
    // Without the filter this per_tank row would be reported as corrupt.
    expect(classify({ ...EMPTY, price_basis: 'per_tank', price_per_unit: 1.585, liters: 45.46, cost: 60 })).toBe('excluded')
    expect(classify({ ...EMPTY, price_basis: 'per_kwh', price_per_unit: 1.585, liters: 45.46, cost: 60 })).toBe('excluded')
    expect(classify({ ...EMPTY, price_basis: null, price_per_unit: 1.585, liters: 45.46, cost: 60 })).toBe('excluded')
  })

  it('CONSTRAINT 2: a propane row carries its volume in propane_liters', () => {
    // PropaneRecordForm writes `liters: undefined` on purpose. 20 gal at
    // 3.00/gal, corrupted: 0.793 x 90.92 / 60 = 1.20166.
    expect(
      classify({ ...EMPTY, price_per_unit: 0.793, liters: null, propane_liters: 90.92, cost: 60 })
    ).toBe('suspect')
    // And a clean propane row is still clean, so the coalesce is not simply
    // treating every propane row as suspect.
    expect(
      classify({ ...EMPTY, price_per_unit: 0.65989, liters: null, propane_liters: 90.922, cost: 60 })
    ).toBe('clean')
  })

  it('CONSTRAINT 3: the rebate is added back before the ratio is taken', () => {
    // The plan's real row: 10 L at 1.00/L with an 8.00 rebate stores cost = 2.
    // Naively 1.0 x 10 / 2 = 5.0, which is neither hypothesis, so a detector
    // that forgets the rebate throws a clean row away (or, on other numbers,
    // reports it).
    expect(
      classify({ ...EMPTY, price_per_unit: 1.0, liters: 10, cost: 2, rebate: 8 })
    ).toBe('clean')
    // With the rebate ignored the same row reads 5.0 and is not evidence.
    expect(classify({ ...EMPTY, price_per_unit: 1.0, liters: 10, cost: 2 })).toBe('excluded')
  })

  it('CONSTRAINT 4: a total that does not reconcile is excluded, not judged', () => {
    // 10 L at $1/L on a $12 receipt: the car wash rode along on the same
    // swipe, which FuelRecordForm preserves deliberately. Ratio 0.833.
    expect(classify({ ...EMPTY, price_per_unit: 1.0, liters: 10, cost: 12 })).toBe('excluded')
    // A discounted total can also land NEAR the corrupt attractor with no UK
    // bug at all, which is why a suspect verdict is a candidate and not proof:
    // 10 L at $1/L on a $8.33 total reads 1.20048.
    expect(classify({ ...EMPTY, price_per_unit: 1.0, liters: 10, cost: 8.33 })).toBe('suspect')
  })

  it('excludes a row with nothing to divide', () => {
    expect(classify({ ...EMPTY, price_per_unit: 1.0, liters: 10, cost: 0 })).toBe('excluded')
    expect(classify({ ...EMPTY, price_per_unit: null, liters: 10, cost: 60 })).toBe('excluded')
    expect(classify({ ...EMPTY, price_per_unit: 1.0, cost: 60 })).toBe('excluded')
    // A complete row on the same shape is judged, so the guards above are
    // rejecting absence rather than everything.
    expect(classify({ ...EMPTY, price_per_unit: 1.0, liters: 10, cost: 10 })).toBe('clean')
  })
})
