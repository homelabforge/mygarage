import { describe, it, expect } from 'vitest'
import { warrantySchema } from '../warranty'

describe('Warranty Schema', () => {
  const validWarranty = {
    warranty_type: 'Manufacturer',
    start_date: '2024-01-15',
  }

  it('validates valid warranty with required fields only', () => {
    const result = warrantySchema.safeParse(validWarranty)
    expect(result.success).toBe(true)
  })

  it('validates warranty with all optional fields', () => {
    const result = warrantySchema.safeParse({
      ...validWarranty,
      provider: 'Ford Motor Company',
      end_date: '2027-01-15',
      mileage_limit: 36000,
      coverage_details: 'Full bumper-to-bumper coverage',
      policy_number: 'W-12345',
      notes: 'Transferable to new owner',
    })
    expect(result.success).toBe(true)
  })

  it('requires warranty_type', () => {
    const result = warrantySchema.safeParse({ start_date: '2024-01-15' })
    expect(result.success).toBe(false)
  })

  it('requires start_date', () => {
    const result = warrantySchema.safeParse({ warranty_type: 'Extended' })
    expect(result.success).toBe(false)
  })

  it('rejects negative mileage_limit', () => {
    const result = warrantySchema.safeParse({
      ...validWarranty,
      mileage_limit: -1000,
    })
    expect(result.success).toBe(false)
  })

  it('transforms NaN mileage_limit to undefined', () => {
    const result = warrantySchema.safeParse({
      ...validWarranty,
      mileage_limit: NaN,
    })
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.mileage_limit).toBeUndefined()
    }
  })

  it('rejects non-integer mileage_limit', () => {
    const result = warrantySchema.safeParse({
      ...validWarranty,
      mileage_limit: 36000.5,
    })
    expect(result.success).toBe(false)
  })
})
