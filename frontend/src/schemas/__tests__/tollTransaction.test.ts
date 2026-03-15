import { describe, it, expect } from 'vitest'
import { tollTransactionSchema } from '../tollTransaction'

describe('Toll Transaction Schema', () => {
  const validTransaction = {
    transaction_date: '2024-03-15',
    location: 'Hardy Toll Road - Main Plaza',
  }

  it('validates valid transaction with required fields only', () => {
    const result = tollTransactionSchema.safeParse(validTransaction)
    expect(result.success).toBe(true)
  })

  it('validates transaction with all optional fields', () => {
    const result = tollTransactionSchema.safeParse({
      ...validTransaction,
      amount: 3.50,
      toll_tag_id: 42,
      notes: 'Regular commute',
    })
    expect(result.success).toBe(true)
  })

  it('requires transaction_date', () => {
    const result = tollTransactionSchema.safeParse({ location: 'Toll Plaza' })
    expect(result.success).toBe(false)
  })

  it('requires location', () => {
    const result = tollTransactionSchema.safeParse({ transaction_date: '2024-03-15' })
    expect(result.success).toBe(false)
  })

  it('rejects negative amount', () => {
    const result = tollTransactionSchema.safeParse({
      ...validTransaction,
      amount: -5.00,
    })
    expect(result.success).toBe(false)
  })

  it('transforms NaN amount to undefined', () => {
    const result = tollTransactionSchema.safeParse({
      ...validTransaction,
      amount: NaN,
    })
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.amount).toBeUndefined()
    }
  })

  it('transforms NaN toll_tag_id to undefined', () => {
    const result = tollTransactionSchema.safeParse({
      ...validTransaction,
      toll_tag_id: NaN,
    })
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.toll_tag_id).toBeUndefined()
    }
  })
})
