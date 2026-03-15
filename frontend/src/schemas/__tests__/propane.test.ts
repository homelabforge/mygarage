import { describe, it, expect } from 'vitest'
import { propaneRecordSchema } from '../propane'

describe('Propane Record Schema', () => {
  const validPropane = {
    date: '2024-09-15',
  }

  it('validates valid propane record with required fields only', () => {
    const result = propaneRecordSchema.safeParse(validPropane)
    expect(result.success).toBe(true)
  })

  it('validates propane record with all optional fields', () => {
    const result = propaneRecordSchema.safeParse({
      ...validPropane,
      propane_gallons: 7.5,
      tank_size_lb: 30,
      tank_quantity: 2,
      price_per_unit: 4.50,
      cost: 33.75,
      vendor: 'U-Haul',
      notes: 'Refilled both 30lb tanks',
    })
    expect(result.success).toBe(true)
  })

  it('requires date', () => {
    const result = propaneRecordSchema.safeParse({})
    expect(result.success).toBe(false)
  })

  it('rejects non-positive propane_gallons', () => {
    const result = propaneRecordSchema.safeParse({
      ...validPropane,
      propane_gallons: 0,
    })
    expect(result.success).toBe(false)
  })

  it('rejects non-integer tank_quantity', () => {
    const result = propaneRecordSchema.safeParse({
      ...validPropane,
      tank_quantity: 1.5,
    })
    expect(result.success).toBe(false)
  })

  it('rejects negative cost', () => {
    const result = propaneRecordSchema.safeParse({
      ...validPropane,
      cost: -10,
    })
    expect(result.success).toBe(false)
  })

  it('transforms NaN numeric fields to undefined', () => {
    const result = propaneRecordSchema.safeParse({
      ...validPropane,
      propane_gallons: NaN,
      tank_size_lb: NaN,
      cost: NaN,
    })
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.propane_gallons).toBeUndefined()
      expect(result.data.tank_size_lb).toBeUndefined()
      expect(result.data.cost).toBeUndefined()
    }
  })

  it('rejects vendor over 100 characters', () => {
    const result = propaneRecordSchema.safeParse({
      ...validPropane,
      vendor: 'A'.repeat(101),
    })
    expect(result.success).toBe(false)
  })
})
