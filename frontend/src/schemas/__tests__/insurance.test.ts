import { describe, it, expect } from 'vitest'
import { insuranceSchema } from '../insurance'

describe('Insurance Schema', () => {
  const validInsurance = {
    provider: 'State Farm',
    policy_number: 'POL-2024-12345',
    policy_type: 'Full Coverage',
    start_date: '2024-01-01',
    end_date: '2024-12-31',
  }

  it('validates valid insurance with required fields only', () => {
    const result = insuranceSchema.safeParse(validInsurance)
    expect(result.success).toBe(true)
  })

  it('validates insurance with all optional fields', () => {
    const result = insuranceSchema.safeParse({
      ...validInsurance,
      premium_amount: '150.00',
      premium_frequency: 'Monthly',
      deductible: '500',
      coverage_limits: '100/300/100',
      notes: 'Multi-vehicle discount applied',
    })
    expect(result.success).toBe(true)
  })

  it('requires provider', () => {
    const { provider: _provider, ...missing } = validInsurance
    const result = insuranceSchema.safeParse(missing)
    expect(result.success).toBe(false)
  })

  it('requires policy_number', () => {
    const { policy_number: _policy_number, ...missing } = validInsurance
    const result = insuranceSchema.safeParse(missing)
    expect(result.success).toBe(false)
  })

  it('requires policy_type', () => {
    const { policy_type: _policy_type, ...missing } = validInsurance
    const result = insuranceSchema.safeParse(missing)
    expect(result.success).toBe(false)
  })

  it('requires start_date', () => {
    const { start_date: _start_date, ...missing } = validInsurance
    const result = insuranceSchema.safeParse(missing)
    expect(result.success).toBe(false)
  })

  it('requires end_date', () => {
    const { end_date: _end_date, ...missing } = validInsurance
    const result = insuranceSchema.safeParse(missing)
    expect(result.success).toBe(false)
  })
})
