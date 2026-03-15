import { describe, it, expect } from 'vitest'
import { spotRentalBillingSchema } from '../spotRentalBilling'

describe('Spot Rental Billing Schema', () => {
  const validBilling = {
    billing_date: '2024-08-01',
  }

  it('validates valid billing with required fields only', () => {
    const result = spotRentalBillingSchema.safeParse(validBilling)
    expect(result.success).toBe(true)
  })

  it('validates billing with all optional fields', () => {
    const result = spotRentalBillingSchema.safeParse({
      ...validBilling,
      monthly_rate: 800.00,
      electric: 45.50,
      water: 12.00,
      waste: 20.00,
      total: 877.50,
      notes: 'August billing cycle',
    })
    expect(result.success).toBe(true)
  })

  it('requires billing_date', () => {
    const result = spotRentalBillingSchema.safeParse({})
    expect(result.success).toBe(false)
  })

  it('rejects negative monthly_rate', () => {
    const result = spotRentalBillingSchema.safeParse({
      ...validBilling,
      monthly_rate: -100,
    })
    expect(result.success).toBe(false)
  })

  it('rejects negative utility costs', () => {
    const result = spotRentalBillingSchema.safeParse({
      ...validBilling,
      electric: -10,
    })
    expect(result.success).toBe(false)
  })

  it('transforms NaN values to undefined', () => {
    const result = spotRentalBillingSchema.safeParse({
      ...validBilling,
      monthly_rate: NaN,
      electric: NaN,
      water: NaN,
      waste: NaN,
      total: NaN,
    })
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.monthly_rate).toBeUndefined()
      expect(result.data.electric).toBeUndefined()
      expect(result.data.water).toBeUndefined()
      expect(result.data.waste).toBeUndefined()
      expect(result.data.total).toBeUndefined()
    }
  })

  it('rejects notes over 1000 characters', () => {
    const result = spotRentalBillingSchema.safeParse({
      ...validBilling,
      notes: 'A'.repeat(1001),
    })
    expect(result.success).toBe(false)
  })
})
