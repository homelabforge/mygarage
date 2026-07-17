import { describe, expect, it } from 'vitest'

import { supplySchema } from '../supplies'

describe('Supply Schema', () => {
  const validEntry = {
    name: 'Motor Oil 5W-30',
    unit_type: 'volume' as const,
  }

  it('validates a valid entry with required fields only', () => {
    const result = supplySchema.safeParse(validEntry)
    expect(result.success).toBe(true)
  })

  it('validates an entry with all optional fields', () => {
    const result = supplySchema.safeParse({
      ...validEntry,
      part_number: 'MO-5W30-QT',
      category: 'Fluids',
      notes: 'Full synthetic',
      vin: '1HGCM82633A004352',
    })
    expect(result.success).toBe(true)
  })

  it('requires name', () => {
    const result = supplySchema.safeParse({ unit_type: 'volume' })
    expect(result.success).toBe(false)
  })

  it('rejects name over 120 characters', () => {
    const result = supplySchema.safeParse({
      ...validEntry,
      name: 'A'.repeat(121),
    })
    expect(result.success).toBe(false)
  })

  it('requires unit_type', () => {
    const result = supplySchema.safeParse({ name: 'Air Filter' })
    expect(result.success).toBe(false)
  })

  it('accepts unit_type "count"', () => {
    const result = supplySchema.safeParse({ name: 'Air Filter', unit_type: 'count' })
    expect(result.success).toBe(true)
  })

  it('rejects an invalid unit_type', () => {
    const result = supplySchema.safeParse({ name: 'Air Filter', unit_type: 'weight' })
    expect(result.success).toBe(false)
  })

  it('allows empty string vin (shared across all vehicles)', () => {
    const result = supplySchema.safeParse({ ...validEntry, vin: '' })
    expect(result.success).toBe(true)
  })

  it('rejects a malformed vin', () => {
    const result = supplySchema.safeParse({ ...validEntry, vin: 'not-a-vin' })
    expect(result.success).toBe(false)
  })

  it('rejects part_number over 60 characters', () => {
    const result = supplySchema.safeParse({
      ...validEntry,
      part_number: 'A'.repeat(61),
    })
    expect(result.success).toBe(false)
  })

  it('rejects category over 40 characters', () => {
    const result = supplySchema.safeParse({
      ...validEntry,
      category: 'A'.repeat(41),
    })
    expect(result.success).toBe(false)
  })
})
