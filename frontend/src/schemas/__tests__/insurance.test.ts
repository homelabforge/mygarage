import { describe, it, expect } from 'vitest'
import type { TFunction } from 'i18next'
import {
  POLICY_TYPES,
  makeInsuranceSchema,
  makeRenewSchema,
  policyTypeLabel,
  policyTypeOptions,
} from '../insurance'
import { MONEY_MAX } from '../shared'

// The i18n mock elsewhere in the suite echoes keys back; do the same here so
// a failed assertion shows the offending key instead of a component-owned
// string this module has no business rendering.
const t = ((k: string) => k) as unknown as TFunction
const schema = makeInsuranceSchema(t)

const vehicle = (over: Record<string, unknown> = {}) => ({
  vin: 'RAMVIN00000000001',
  policy_type: 'Full Coverage',
  coverages: [],
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

  // A collector-car or commercial premium runs past the old 99,999.99
  // currency cap. Both sides cap at MONEY_MAX now (money-fits).
  it('accepts a premium past the old 99,999.99 cap', () => {
    expect(schema.safeParse(policy({ premium_amount: 250000 })).success).toBe(true)
  })

  it('refuses a cent past MONEY_MAX on the policy, a vehicle and a coverage', () => {
    const coverage = (over: Record<string, unknown>) => ({ coverage_key: 'collision', included: true, ...over })
    const at = [
      policy({ premium_amount: MONEY_MAX }),
      policy({ vehicles: [vehicle({ premium_share: MONEY_MAX, deductible: MONEY_MAX })] }),
      policy({ vehicles: [vehicle({ coverages: [coverage({ limit_primary: MONEY_MAX, premium: MONEY_MAX })] })] }),
    ]
    for (const candidate of at) expect(schema.safeParse(candidate).success).toBe(true)

    const over = MONEY_MAX + 0.01
    expect(messages(policy({ premium_amount: over }))).toContain('common:validation.amount.tooLarge')
    expect(messages(policy({ vehicles: [vehicle({ premium_share: over })] }))).toContain('common:validation.amount.tooLarge')
    expect(messages(policy({ vehicles: [vehicle({ deductible: over })] }))).toContain('common:validation.amount.tooLarge')
    for (const field of ['limit_primary', 'limit_secondary', 'deductible', 'premium']) {
      expect(
        messages(policy({ vehicles: [vehicle({ coverages: [coverage({ [field]: over })] })] })),
        field,
      ).toContain('common:validation.amount.tooLarge')
    }
    const renew = makeRenewSchema(t, '2026-01-01').safeParse({
      start_date: '2026-01-01',
      end_date: '2027-01-01',
      premium_amount: over,
    })
    expect(renew.success).toBe(false)
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
  const renew = makeRenewSchema(t, '2026-07-01')

  it('needs both dates in order', () => {
    expect(renew.safeParse({ start_date: '2026-07-01', end_date: '2027-01-01' }).success).toBe(true)
    expect(renew.safeParse({ start_date: '2026-07-01', end_date: '2026-06-01' }).success).toBe(false)
    expect(renew.safeParse({ start_date: '', end_date: '2027-01-01' }).success).toBe(false)
  })

  it('refuses a next term that starts before the current one ends (PR #177 review)', () => {
    const result = renew.safeParse({ start_date: '2026-06-30', end_date: '2027-01-01' })
    expect(result.success).toBe(false)
    if (!result.success) {
      expect(result.error.issues.map((issue) => issue.message)).toContain('forms:insurance.renewOverlaps')
    }
    // The shared boundary day is how declarations pages print adjacent terms.
    expect(renew.safeParse({ start_date: '2026-07-01', end_date: '2027-01-01' }).success).toBe(true)
  })

  it('takes an optional premium', () => {
    expect(
      renew.safeParse({ start_date: '2026-07-01', end_date: '2027-01-01', premium_amount: 684 }).success
    ).toBe(true)
  })
})

describe('European formulas and the no-claims class (#211)', () => {
  it('lists the two European formulas after the North American ones', () => {
    expect(POLICY_TYPES.map((option) => option.value)).toEqual([
      'Liability', 'Comprehensive', 'Collision', 'Full Coverage', 'Minimum', 'Other',
      'Third Party', 'Third Party Extended',
    ])
  })

  it('labels a known type by its key and shows an unknown stored type as it is', () => {
    expect(policyTypeLabel('Third Party', t)).toBe('forms:policyTypes.thirdParty')
    expect(policyTypeLabel('Vintage', t)).toBe('Vintage')
    expect(policyTypeLabel(null, t)).toBe('')
  })

  it("offers the profile's formulas first, in its order, then every other one, ignoring an unknown", () => {
    const values = policyTypeOptions(t, ['Full Coverage', 'Gold', 'Third Party']).map((o) => o.value)
    expect(values.slice(0, 2)).toEqual(['Full Coverage', 'Third Party'])
    expect(values).toHaveLength(POLICY_TYPES.length)
    expect(new Set(values).size).toBe(POLICY_TYPES.length)
    expect(policyTypeOptions(t, undefined).map((o) => o.value)).toEqual(POLICY_TYPES.map((o) => o.value))
    expect(policyTypeOptions(t, ['Third Party'])[0].label).toBe('forms:policyTypes.thirdParty')
  })

  it('accepts a short no-claims class, an empty one, and refuses one the API would', () => {
    expect(schema.safeParse(policy({ vehicles: [vehicle({ no_claims_class: '0.50' })] })).success).toBe(true)
    expect(schema.safeParse(policy({ vehicles: [vehicle({ no_claims_class: 'SF 12' })] })).success).toBe(true)
    expect(schema.safeParse(policy({ vehicles: [vehicle({ no_claims_class: '' })] })).success).toBe(true)
    expect(schema.safeParse(policy({ vehicles: [vehicle({})] })).success).toBe(true)
    expect(messages(policy({ vehicles: [vehicle({ no_claims_class: 'a class far too long' })] }))).toContain(
      'forms:insurance.noClaimsClassInvalid'
    )
    expect(messages(policy({ vehicles: [vehicle({ no_claims_class: '0.50€' })] }))).toContain(
      'forms:insurance.noClaimsClassInvalid'
    )
  })
})
