/**
 * The entry grid's round trip: a stored value, reopened and saved untouched.
 *
 * ★ WHY A MATRIX AND NOT A FIXTURE. Phase 3a proved a per-cycle drift with one
 * value, `72420.3`, and that value is the one that does NOT drift: it
 * round-trips exactly, so the fixture was accidentally a fixed point and the
 * proof was a coincidence. A single value cannot tell an exact round trip from
 * a lucky one, so this enumerates the whole cross product of the vocabulary
 * (every volume token a resolved set can name) against a value list that
 * deliberately includes both fixed points and the extremes of the wire range.
 *
 * ★ AND EVERY CASE CARRIES ITS OWN "THIS IS NOT VACUOUS" FLAG. Asserting that
 * the protocol returns the stored value is satisfied for free by any value
 * whose display happens to convert back exactly, and 9 of the 27 volume
 * combinations below are exactly that. So each case also computes the NAIVE
 * answer: convert the display string back through the same adapter, with no
 * origin. The count of combinations where the two differ is asserted, so a
 * change that quietly made the naive path exact (a wider display precision,
 * say) would fail here rather than hollow the file out.
 *
 * ★ `naive` IS THIS SEED WITH THE ORIGIN REMOVED, NOT WHAT SHIPPED, and the
 * difference matters for the nine metric volume rows. What shipped seeded a
 * metric volume field through `litersToVolumeUnit`, which returns the raw
 * stored litres unrounded, so those nine did not move at all: the shipped
 * count was 13 of 27 and this column's is 18. Both are true statements about
 * different questions. This column answers "is the origin load bearing for
 * this row, given the seed the field has NOW", which is the only question a
 * committed test can keep answering once the old seed is deleted.
 *
 * Set `UNITS_MATRIX=1` to print the raw table. It is off by default because
 * 54 lines of stdout per suite run is noise; it is available at all because a
 * measurement nobody can reproduce is a number in prose.
 */

import { describe, expect, it } from 'vitest'
import { makeUnitSet } from '@/__tests__/factories'
import {
  canonicalFromPriceField,
  priceToDisplay,
  seedPriceField,
  toLitersWirePrecision,
} from '../decimalSafe'
import { canonicalFromUnitField, makeUnitFormat, seedUnitField } from '../unitFormat'
import type { UnitSet } from '@/types/units'

/** Every volume token a resolved set can name, each with its own gallon. */
const SETS: readonly { name: string; units: UnitSet }[] = [
  { name: 'L', units: makeUnitSet() },
  { name: 'gal_us', units: makeUnitSet({ volume: 'gal_us', secondary_gallon: 'us' }) },
  { name: 'gal_uk', units: makeUnitSet({ volume: 'gal_uk', secondary_gallon: 'uk' }) },
]

/**
 * Nine stored litre values: two fixed points, both wire extremes, and five
 * ordinary fills.
 *
 * `45.461` is exactly ten imperial gallons and `47.318` is very nearly twelve
 * and a half US ones, so each is a fixed point for ONE set and not for the
 * others: a matrix in which every value round-tripped for every set would
 * prove nothing. `0.001` is the smallest value the wire can carry and `9999.999`
 * the largest the schema accepts (`le=9999.999`).
 */
const LITRES = [0, 0.001, 1, 12.345, 37.9, 45.461, 47.318, 72.42, 9999.999]

/**
 * Nine stored canonical prices, in $/L.
 *
 * `1.234567` is the value the ruling quotes: it came back `1.23446742145` from
 * the shipped round trip. The rest are real pump prices plus both ends of the
 * column's range (`Numeric(6, 3)`, `le=999.999`).
 */
const PRICES = [0, 0.001, 0.898, 1.136, 1.189, 1.234567, 1.4499, 2.899, 999.999]

/** One combination's before and after. */
interface Row {
  set: string
  canonical: number
  seeded: string
  /** What the protocol posts for a field the user never touched. */
  kept: number | null
  /** What the shipped path posted: the display, reconverted. */
  naive: number | null
}

/** Seed a volume field and read it straight back, both ways. */
function volumeRow(set: { name: string; units: UnitSet }, canonical: number): Row {
  const quantity = makeUnitFormat(set.units).volume
  const origin = seedUnitField(canonical, quantity)
  return {
    set: set.name,
    canonical,
    seeded: origin.display,
    kept: toLitersWirePrecision(canonicalFromUnitField(origin.display, origin, quantity)),
    naive: toLitersWirePrecision(quantity.toCanonical(Number(origin.display))),
  }
}

/** The same for a price field, at the `per_volume` basis all three writers use. */
function priceRow(set: { name: string; units: UnitSet }, canonical: number): Row {
  const origin = seedPriceField(canonical, set.units, 'per_volume')
  const naiveDisplay = priceToDisplay(canonical, set.units, 'per_volume')
  return {
    set: set.name,
    canonical,
    seeded: origin.display,
    kept: canonicalFromPriceField(origin.display, origin, set.units, 'per_volume'),
    // The shipped path: the same display, converted back with no origin. An
    // unseeded origin is exactly "no origin", so this is the production read
    // with the one thing this task added taken away.
    naive: canonicalFromPriceField(
      String(naiveDisplay ?? ''),
      { canonical: null, display: '', basis: 'per_volume' },
      set.units,
      'per_volume'
    ),
  }
}

/**
 * Print the table when asked, so the measurement is reproducible.
 *
 * Straight to `process.stdout` rather than through `console.log`, which vitest
 * intercepts and buffers per test: a table nobody can see is the same as a
 * number written down in prose, which is the thing this file exists to avoid.
 */
function report(title: string, rows: readonly Row[]): void {
  if (process.env.UNITS_MATRIX !== '1') return
  const pad = (v: unknown, n: number): string => String(v).padEnd(n)
  const lines = rows.map(
    (r) =>
      `${pad(r.set, 8)} ${pad(r.canonical, 14)} ${pad(r.seeded, 14)} ${pad(r.kept, 14)} ${r.naive}`
  )
  process.stdout.write(
    `\n${title}\nset      canonical      seeded         kept           naive\n${lines.join('\n')}\n`
  )
}

const volumeRows = SETS.flatMap((set) => LITRES.map((v) => volumeRow(set, v)))
const priceRows = SETS.flatMap((set) => PRICES.map((v) => priceRow(set, v)))

describe('the entry grid round trip, over the whole vocabulary', () => {
  it('enumerates the cross product rather than sampling it', () => {
    // The receipt. A list that silently lost a set or a value would make every
    // assertion below true of a smaller universe than the one named.
    expect(SETS.map((s) => s.name)).toStrictEqual(['L', 'gal_us', 'gal_uk'])
    expect(volumeRows).toHaveLength(27)
    expect(priceRows).toHaveLength(27)
    report('VOLUME', volumeRows)
    report('PRICE', priceRows)
  })

  it('★ VOLUME: an untouched save posts the stored litres, in all 27 combinations', () => {
    const moved = volumeRows.filter((r) => r.kept !== r.canonical)
    expect(moved).toStrictEqual([])
  })

  it('★ PRICE: an untouched save posts the stored $/L, in all 27 combinations', () => {
    const moved = priceRows.filter((r) => r.kept !== r.canonical)
    expect(moved).toStrictEqual([])
  })

  it('is not satisfied by combinations that round-trip anyway', () => {
    // ★ The anti-vacuity leg. Without it both assertions above would still pass
    // on a build where the origin did nothing at all, for every value whose
    // display happens to reconvert exactly. These counts are the measurement:
    // they say how many of the 27 the origin is actually load bearing for.
    const volumeNaive = volumeRows.filter((r) => r.naive !== r.canonical)
    const priceNaive = priceRows.filter((r) => r.naive !== r.canonical)
    expect(volumeNaive.length).toBe(18)
    expect(priceNaive.length).toBe(16)
    // And the two fixed points are real: `45.461` is ten imperial gallons and
    // `47.318` is twelve and a half US ones, so each set has values the naive
    // path gets right. A matrix where EVERY row moved would mean the display
    // precision, not the origin, was the thing under test.
    expect(volumeNaive.length).toBeLessThan(volumeRows.length)
    expect(priceNaive.length).toBeLessThan(priceRows.length)
  })

  it('★ carries the value the ruling quotes, and the answer it used to give', () => {
    // Named rather than left inside the matrix: `1.234567` $/L on imperial
    // gallons is the case R4 cites, and it came back `1.23446742145`.
    const row = priceRows.find((r) => r.set === 'gal_uk' && r.canonical === 1.234567)!
    expect(row.seeded).toBe('5.612')
    expect(row.naive).toBe(1.23446742145)
    expect(row.kept).toBe(1.234567)
  })

  it('★ carries the value phase 3a proved a drift with, which does NOT drift', () => {
    // 72420.3 is the odometer fixture whose exactness made 3a's proof a
    // coincidence. Its volume analogue here is `45.461` on imperial gallons:
    // ten gallons exactly, so the naive path is right and the case proves
    // nothing on its own. Stated so nobody promotes it to the proof.
    const row = volumeRows.find((r) => r.set === 'gal_uk' && r.canonical === 45.461)!
    expect(row.seeded).toBe('10.00')
    expect(row.naive).toBe(45.461)
    expect(row.kept).toBe(45.461)
  })
})
