import { describe, expect, it } from 'vitest'
import { estimateUsageCost, sameQuantity } from '../supplyUsageCost'
import { toCanonical, toDisplay } from '../supplyUnits'

// What the form shows for a usage must be what the server will store (#301).
describe('estimateUsageCost', () => {
  it('a saved usage at its saved quantity shows its stored cost, not the average', () => {
    const saved = { quantity: '4.7317647300000', unit_cost_snapshot: '7.9146', cost_snapshot: '37.45' }
    expect(estimateUsageCost(4.73176473, saved, '9.0000')).toEqual({ cost: 37.45, unpriced: false, backfill: false, estimated: false })
  })

  it('a stored cost wins even when it is not unit × quantity (an import)', () => {
    const saved = { quantity: '3', unit_cost_snapshot: null, cost_snapshot: '12.00' }
    expect(estimateUsageCost(3, saved, '9.0000')).toEqual({ cost: 12, unpriced: false, backfill: false, estimated: false })
  })

  it('a zero cost is a price, not a gap', () => {
    const saved = { quantity: '1', unit_cost_snapshot: '0.0000', cost_snapshot: '0.00' }
    expect(estimateUsageCost(1, saved, null)).toEqual({ cost: 0, unpriced: false, backfill: false, estimated: false })
  })

  it('a changed quantity reprices at the frozen unit cost, like the server', () => {
    const saved = { quantity: '5', unit_cost_snapshot: '7.0000', cost_snapshot: '35.00' }
    expect(estimateUsageCost(6, saved, '9.0000')).toEqual({ cost: 42, unpriced: false, backfill: false, estimated: false })
  })

  it('a cost-only row whose quantity changed falls to the average, like the server', () => {
    // The edit leaves it with no cost; the backfill after it prices it, as of the visit.
    const saved = { quantity: '3', unit_cost_snapshot: null, cost_snapshot: '12.00' }
    expect(estimateUsageCost(4, saved, '9.0000')).toEqual({ cost: 36, unpriced: false, backfill: true, estimated: true })
  })

  it('a unit-only row gets unit × quantity, which the save stores', () => {
    const saved = { quantity: '2', unit_cost_snapshot: '5.0000', cost_snapshot: null }
    expect(estimateUsageCost(2, saved, '9.0000')).toEqual({ cost: 10, unpriced: false, backfill: true, estimated: false })
  })

  it('an unpriced saved row and a new usage price at the average, as an estimate', () => {
    // The server prices both as of the visit date, which the average may not be (#307).
    const saved = { quantity: '5', unit_cost_snapshot: null, cost_snapshot: null }
    expect(estimateUsageCost(5, saved, '8.0000')).toEqual({ cost: 40, unpriced: false, backfill: true, estimated: true })
    // A new usage is priced by the edit, so it's no backfill.
    expect(estimateUsageCost(5, undefined, '8.0000')).toEqual({ cost: 40, unpriced: false, backfill: false, estimated: true })
  })

  it('nothing to price with is unpriced, and counts as nothing', () => {
    expect(estimateUsageCost(5, undefined, null)).toEqual({ cost: 0, unpriced: true, backfill: false, estimated: false })
    expect(estimateUsageCost(5, { quantity: '5', unit_cost_snapshot: null, cost_snapshot: null }, undefined))
      .toEqual({ cost: 0, unpriced: true, backfill: false, estimated: false })
  })

  // #307: an estimate is the all-time average standing in for an as-of price.
  // The visit pricer settles it inside its savepoint, so it isn't fixed.
  describe('a saved estimate', () => {
    const estimate = { quantity: '5', unit_cost_snapshot: '7.4900', cost_snapshot: '37.45', cost_estimated: true }

    it('shows its stored cost, but as an estimate the save may move', () => {
      expect(estimateUsageCost(5, estimate, '9.0000')).toEqual({ cost: 37.45, unpriced: false, backfill: true, estimated: true })
    })

    it('stays an estimate at a new quantity, priced at its own unit like the edit does', () => {
      expect(estimateUsageCost(6, estimate, '9.0000')).toEqual({ cost: 44.94, unpriced: false, backfill: true, estimated: true })
    })

    it('a settled usage is fixed, the same row unflagged', () => {
      expect(estimateUsageCost(5, { ...estimate, cost_estimated: false }, '9.0000'))
        .toEqual({ cost: 37.45, unpriced: false, backfill: false, estimated: false })
    })
  })

  // A date change re-prices any usage on the visit, frozen ones too (D3, N-2).
  // It happens in the edit itself, so the bucket doesn't move; only the label does.
  describe('with the visit date changed', () => {
    const dateChanged = { dateChanged: true }

    it('a frozen usage at its quantity is an estimate', () => {
      const saved = { quantity: '5', unit_cost_snapshot: '7.0000', cost_snapshot: '35.00' }
      expect(estimateUsageCost(5, saved, '9.0000', dateChanged)).toEqual({ cost: 35, unpriced: false, backfill: false, estimated: true })
    })

    it('a frozen usage at a new quantity is an estimate', () => {
      const saved = { quantity: '5', unit_cost_snapshot: '7.0000', cost_snapshot: '35.00' }
      expect(estimateUsageCost(6, saved, '9.0000', dateChanged)).toEqual({ cost: 42, unpriced: false, backfill: false, estimated: true })
    })

    it('a unit-only row is an estimate', () => {
      const saved = { quantity: '2', unit_cost_snapshot: '5.0000', cost_snapshot: null }
      expect(estimateUsageCost(2, saved, '9.0000', dateChanged)).toEqual({ cost: 10, unpriced: false, backfill: true, estimated: true })
    })

    it('nothing to price with is still unpriced, not an estimate', () => {
      expect(estimateUsageCost(5, { quantity: '5', unit_cost_snapshot: null, cost_snapshot: null }, null, dateChanged))
        .toEqual({ cost: 0, unpriced: true, backfill: false, estimated: false })
    })
  })

  it('rounds half a cent up, as the server does, not down as float maths would', () => {
    expect(1.005 * 100).toBeLessThan(100.5) // the float trap this avoids
    expect(estimateUsageCost(1, undefined, '1.0050').cost).toBe(1.01)
    expect(estimateUsageCost(4.73176473, undefined, '7.9146').cost).toBe(37.45)
  })
})

describe('sameQuantity', () => {
  it('ignores the noise a display round trip adds', () => {
    // UK quarts: a canonical value back from display isn't bit-identical.
    let drifted = 0
    for (let i = 1; i <= 4000; i++) {
      const canonical = Number((i / 100).toFixed(2))
      const back = toCanonical(toDisplay(canonical, 'qt_uk'), 'qt_uk')
      if (back !== canonical) drifted++
      expect(sameQuantity(back, canonical.toFixed(13))).toBe(true)
    }
    expect(drifted).toBeGreaterThan(0) // the case is real, not hypothetical
  })

  it('rounds the number once, from the text the request sends', () => {
    // JSON sends 1.000000000000045 and the server rounds it down to 1. Rounded
    // at 14 places first it read ...05, and went up.
    expect(sameQuantity(1.000000000000045, '1.0000000000000')).toBe(true)
    expect(sameQuantity(1.00000000000005, '1.0000000000001')).toBe(true)
  })

  it('reads a number String writes with an exponent', () => {
    expect(sameQuantity(1e-7, '0.0000001000000')).toBe(true)
    expect(sameQuantity(1.5e-14, '0.0000000000000')).toBe(true)
    expect(sameQuantity(5e-14, '0.0000000000001')).toBe(true)
  })

  it('still sees a real change', () => {
    expect(sameQuantity(5.0000000000001, '5.0000000000000')).toBe(false)
    expect(sameQuantity(5.1, '5')).toBe(false)
  })
})
