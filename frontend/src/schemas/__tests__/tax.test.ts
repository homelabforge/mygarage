import { describe, it, expect } from 'vitest'
import { taxRecordSchema, TAX_TYPES } from '../tax'

describe('Tax Record Schema', () => {
  const validTax = {
    date: '2024-06-15',
    amount: 125.50,
  }

  it('validates valid tax record with required fields only', () => {
    const result = taxRecordSchema.safeParse(validTax)
    expect(result.success).toBe(true)
  })

  it('validates tax record with all optional fields', () => {
    const result = taxRecordSchema.safeParse({
      ...validTax,
      tax_type: 'Registration',
      renewal_date: '2025-06-15',
      notes: 'Annual vehicle registration renewal',
    })
    expect(result.success).toBe(true)
  })

  it('requires date in YYYY-MM-DD format', () => {
    const result = taxRecordSchema.safeParse({
      ...validTax,
      date: '06/15/2024',
    })
    expect(result.success).toBe(false)
  })

  it('rejects negative amount', () => {
    const result = taxRecordSchema.safeParse({
      ...validTax,
      amount: -50,
    })
    expect(result.success).toBe(false)
  })

  it('rejects amount exceeding max', () => {
    const result = taxRecordSchema.safeParse({
      ...validTax,
      amount: 100000,
    })
    expect(result.success).toBe(false)
  })

  it('accepts all valid tax types', () => {
    for (const taxType of TAX_TYPES) {
      const result = taxRecordSchema.safeParse({ ...validTax, tax_type: taxType })
      expect(result.success).toBe(true)
    }
  })

  it('rejects invalid tax type', () => {
    const result = taxRecordSchema.safeParse({
      ...validTax,
      tax_type: 'Income Tax',
    })
    expect(result.success).toBe(false)
  })
})
