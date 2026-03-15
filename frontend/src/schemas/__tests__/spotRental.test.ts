import { describe, it, expect } from 'vitest'
import { spotRentalSchema } from '../spotRental'

describe('Spot Rental Schema', () => {
  const validRental = {
    check_in_date: '2024-07-01',
  }

  it('validates valid spot rental with required fields only', () => {
    const result = spotRentalSchema.safeParse(validRental)
    expect(result.success).toBe(true)
  })

  it('validates spot rental with all optional fields', () => {
    const result = spotRentalSchema.safeParse({
      ...validRental,
      location_name: 'Jellystone Park',
      location_address: '123 Camp Rd',
      check_out_date: '2024-07-07',
      nightly_rate: 55.00,
      weekly_rate: 350.00,
      monthly_rate: 1200.00,
      electric: 25.00,
      water: 10.00,
      waste: 15.00,
      total_cost: 400.00,
      amenities: 'Full hookup, WiFi, Pool',
      notes: 'Pull-through site #42',
    })
    expect(result.success).toBe(true)
  })

  it('requires check_in_date in YYYY-MM-DD format', () => {
    const result = spotRentalSchema.safeParse({
      check_in_date: 'July 1, 2024',
    })
    expect(result.success).toBe(false)
  })

  it('rejects negative nightly_rate', () => {
    const result = spotRentalSchema.safeParse({
      ...validRental,
      nightly_rate: -10,
    })
    expect(result.success).toBe(false)
  })

  it('rejects nightly_rate exceeding max', () => {
    const result = spotRentalSchema.safeParse({
      ...validRental,
      nightly_rate: 10000,
    })
    expect(result.success).toBe(false)
  })

  it('rejects negative utility cost', () => {
    const result = spotRentalSchema.safeParse({
      ...validRental,
      electric: -5,
    })
    expect(result.success).toBe(false)
  })

  it('rejects location_name over 100 characters', () => {
    const result = spotRentalSchema.safeParse({
      ...validRental,
      location_name: 'A'.repeat(101),
    })
    expect(result.success).toBe(false)
  })

  it('transforms NaN nightly_rate to undefined', () => {
    const result = spotRentalSchema.safeParse({
      ...validRental,
      nightly_rate: NaN,
    })
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.nightly_rate).toBeUndefined()
    }
  })
})
