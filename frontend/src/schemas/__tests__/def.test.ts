import { describe, it, expect } from 'vitest'
import { defRecordSchema } from '../def'

describe('DEF Record Schema', () => {
  const validDef = {
    date: '2024-04-10',
  }

  it('validates valid DEF record with required fields only', () => {
    const result = defRecordSchema.safeParse(validDef)
    expect(result.success).toBe(true)
  })

  it('validates DEF record with all optional fields', () => {
    const result = defRecordSchema.safeParse({
      ...validDef,
      odometer_km: 45000,
      liters: 2.5,
      price_per_unit: 3.99,
      cost: 9.98,
      fill_level: 75,
      source: 'Truck Stop',
      brand: 'Blue DEF',
      notes: 'Topped off at half tank',
    })
    expect(result.success).toBe(true)
  })

  it('requires date in YYYY-MM-DD format', () => {
    const result = defRecordSchema.safeParse({ date: '04-10-2024' })
    expect(result.success).toBe(false)
  })

  it('rejects fill_level below 0', () => {
    const result = defRecordSchema.safeParse({
      ...validDef,
      fill_level: -1,
    })
    expect(result.success).toBe(false)
  })

  it('rejects fill_level above 100', () => {
    const result = defRecordSchema.safeParse({
      ...validDef,
      fill_level: 101,
    })
    expect(result.success).toBe(false)
  })

  it('transforms NaN fill_level to undefined', () => {
    const result = defRecordSchema.safeParse({
      ...validDef,
      fill_level: NaN,
    })
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.fill_level).toBeUndefined()
    }
  })

  it('rejects negative mileage', () => {
    const result = defRecordSchema.safeParse({
      ...validDef,
      odometer_km: -100,
    })
    expect(result.success).toBe(false)
  })

  it('rejects source over 100 characters', () => {
    const result = defRecordSchema.safeParse({
      ...validDef,
      source: 'A'.repeat(101),
    })
    expect(result.success).toBe(false)
  })
})
