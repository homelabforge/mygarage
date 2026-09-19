import { describe, it, expect } from 'vitest'
import type { TFunction } from 'i18next'
import { makeInsuranceSchema, makeRenewSchema } from '../insurance'

// The i18n mock elsewhere in the suite echoes keys back; do the same here so
// a failed assertion shows the offending key instead of a component-owned
// string this module has no business rendering.
const t = ((k: string) => k) as unknown as TFunction
const schema = makeInsuranceSchema(t)

const vehicle = (over: Record<string, unknown> = {}) => ({
  vin: 'RAMVIN00000000001',
  policy_type: 'Full Coverage',
  fields: [],
  ...over,
})

const policy = (over: Record<string, unknown> = {}) => ({
  provider: 'State Farm',
  policy_number: 'POL-2024-12345',
  start_date: '2026-01-01',
  end_date: '2026-12-31',
  fields: [],
  vehicles: [],
  ...over,
})

const messages = (input: unknown): string[] => {
  const result = schema.safeParse(input)
  return result.success ? [] : result.error.issues.map((issue) => issue.message)
}

describe('Insurance policy schema', () => {
  it('accepts a policy with no vehicles: an umbrella policy covers none', () => {
    expect(schema.safeParse(policy()).success).toBe(true)
  })

  // premium_amount is an ABSENT key here, not an undefined one:
  // `z.unknown().optional()` treats the two differently (see schemas/shared.ts),
  // so this is the case that exercises that trap.
  it('accepts an absent premium, and a vehicle with no share or deductible', () => {
    const result = schema.safeParse(policy({ vehicles: [vehicle()] }))
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.premium_amount).toBeUndefined()
      expect(result.data.vehicles[0].premium_share).toBeUndefined()
    }
  })

  it.each(['provider', 'policy_number', 'start_date', 'end_date'])('requires %s', (name) => {
    expect(schema.safeParse(policy({ [name]: '' })).success).toBe(false)
  })

  it('requires a coverage type on every vehicle', () => {
    expect(messages(policy({ vehicles: [vehicle({ policy_type: '' })] }))).toContain(
      'common:validation.policyType.required'
    )
  })

  it('reads a comma-decimal premium as a number (#140)', () => {
    const result = schema.safeParse(policy({ premium_amount: 528.25, vehicles: [vehicle({ premium_share: 264.12 })] }))
    expect(result.success).toBe(true)
  })

  it('rejects raw unparsed text and negative amounts, on the policy and on a vehicle', () => {
    expect(schema.safeParse(policy({ premium_amount: 'abc' })).success).toBe(false)
    expect(schema.safeParse(policy({ premium_amount: -1 })).success).toBe(false)
    expect(schema.safeParse(policy({ vehicles: [vehicle({ premium_share: -5 })] })).success).toBe(false)
    expect(schema.safeParse(policy({ vehicles: [vehicle({ deductible: 'abc' })] })).success).toBe(false)
  })

  // The backend has `ge=0` and no ceiling: a collector-car or commercial
  // premium over 99,999.99 must not be refused client-side.
  it('accepts a premium above the generic currency ceiling', () => {
    expect(schema.safeParse(policy({ premium_amount: 250000 })).success).toBe(true)
  })

  it('refuses an end date before the start', () => {
    expect(messages(policy({ start_date: '2026-06-01', end_date: '2026-05-01' }))).toContain(
      'forms:insurance.endBeforeStart'
    )
  })

  it('a named field needs both a label and a value, at either level', () => {
    expect(schema.safeParse(policy({ fields: [{ label: 'Agent Phone', value: '' }] })).success).toBe(false)
    expect(schema.safeParse(policy({ fields: [{ label: ' ', value: '555' }] })).success).toBe(false)
    expect(
      schema.safeParse(
        policy({ vehicles: [vehicle({ fields: [{ label: 'Collision Deductible', value: '$500' }] })] })
      ).success
    ).toBe(true)
  })
})

describe('Renew schema', () => {
  const renew = makeRenewSchema(t)

  it('needs both dates in order, and takes an optional premium', () => {
    expect(renew.safeParse({ start_date: '2026-07-01', end_date: '2027-01-01' }).success).toBe(true)
    expect(renew.safeParse({ start_date: '2026-07-01', end_date: '2026-06-01' }).success).toBe(false)
    expect(renew.safeParse({ start_date: '', end_date: '2027-01-01' }).success).toBe(false)
    expect(
      renew.safeParse({ start_date: '2026-07-01', end_date: '2027-01-01', premium_amount: 684 }).success
    ).toBe(true)
  })
})
