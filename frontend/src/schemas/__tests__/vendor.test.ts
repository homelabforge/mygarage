import { describe, it, expect } from 'vitest'
import { vendorSchema } from '../vendor'

describe('Vendor Schema', () => {
  const validVendor = {
    name: 'AutoZone',
  }

  it('validates valid vendor with required fields only', () => {
    const result = vendorSchema.safeParse(validVendor)
    expect(result.success).toBe(true)
  })

  it('validates vendor with all optional fields', () => {
    const result = vendorSchema.safeParse({
      ...validVendor,
      address: '456 Commerce Dr',
      city: 'Dallas',
      state: 'TX',
      zip_code: '75201',
      phone: '(555) 987-6543',
    })
    expect(result.success).toBe(true)
  })

  it('requires name', () => {
    const result = vendorSchema.safeParse({})
    expect(result.success).toBe(false)
  })

  it('rejects name over 100 characters', () => {
    const result = vendorSchema.safeParse({
      name: 'A'.repeat(101),
    })
    expect(result.success).toBe(false)
  })

  it('validates phone number format', () => {
    const validPhones = ['555-123-4567', '(555) 123-4567', '+1 555 123 4567', '']
    for (const phone of validPhones) {
      const result = vendorSchema.safeParse({ ...validVendor, phone })
      expect(result.success).toBe(true)
    }
  })

  it('rejects invalid phone number characters', () => {
    const result = vendorSchema.safeParse({
      ...validVendor,
      phone: 'call-me-maybe',
    })
    expect(result.success).toBe(false)
  })

  it('rejects address over 200 characters', () => {
    const result = vendorSchema.safeParse({
      ...validVendor,
      address: 'A'.repeat(201),
    })
    expect(result.success).toBe(false)
  })

  it('rejects zip_code over 20 characters', () => {
    const result = vendorSchema.safeParse({
      ...validVendor,
      zip_code: '1'.repeat(21),
    })
    expect(result.success).toBe(false)
  })
})
