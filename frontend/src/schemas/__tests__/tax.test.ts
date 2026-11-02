import { describe, it, expect } from 'vitest'
import type { TFunction } from 'i18next'
import {
  asTaxType,
  LEGACY_TAX_TYPES,
  makeTaxRecordSchema,
  TAX_TYPES,
  TAX_TYPE_VALUES,
  taxTypeLabel,
  taxTypeOptions,
} from '../tax'
import { MONEY_MAX } from '../shared'

// Same shape as the global react-i18next mock in src/__tests__/setup.ts:
// messages come back as their i18n key, which is all these tests need.
const t = ((key: string) => key) as unknown as TFunction

const taxRecordSchema = makeTaxRecordSchema(t)

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
      tax_type: 'registration',
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

  // The cap moved from 99,999.99 to the API's MONEY_MAX (money-fits): a
  // registration tax in forint or yen runs past the old one.
  it('rejects amount exceeding max', () => {
    const result = taxRecordSchema.safeParse({
      ...validTax,
      amount: MONEY_MAX + 0.01,
    })
    expect(result.success).toBe(false)
    if (!result.success) expect(result.error.issues[0].message).toBe('common:validation.amount.tooLarge')
  })

  it('accepts an amount at MONEY_MAX and past the old 99,999.99 cap', () => {
    expect(taxRecordSchema.safeParse({ ...validTax, amount: MONEY_MAX }).success).toBe(true)
    expect(taxRecordSchema.safeParse({ ...validTax, amount: 100000 }).success).toBe(true)
  })

  it('accepts all valid tax types', () => {
    for (const taxType of TAX_TYPE_VALUES) {
      const result = taxRecordSchema.safeParse({ ...validTax, tax_type: taxType })
      expect(result.success).toBe(true)
    }
  })

  it('keeps the TAX_TYPES option list aligned with the persisted values', () => {
    expect(TAX_TYPES.map((option) => option.value)).toEqual([...TAX_TYPE_VALUES])
  })

  it('rejects invalid tax type', () => {
    const result = taxRecordSchema.safeParse({
      ...validTax,
      tax_type: 'Income Tax',
    })
    expect(result.success).toBe(false)
  })

  // The form never posts a legacy spelling: a record carrying one is read as
  // its code (asTaxType) before it reaches the select.
  it('rejects the pre-146 display strings as form values', () => {
    expect(taxRecordSchema.safeParse({ ...validTax, tax_type: 'Property Tax' }).success).toBe(false)
  })
})

describe('Tax type codes (#211)', () => {
  it('reads a code as itself and a legacy display string as its code', () => {
    expect(asTaxType('co2_malus')).toBe('co2_malus')
    expect(asTaxType('Property Tax')).toBe('property_tax')
    expect(asTaxType('Income Tax')).toBeNull()
    expect(asTaxType(null)).toBeNull()
    expect(Object.keys(LEGACY_TAX_TYPES).sort()).toEqual(['Inspection', 'Property Tax', 'Registration', 'Tolls'])
  })

  it('labels a code by its bundle key, with the national name when the profile gives one', () => {
    expect(taxTypeLabel('registration_tax', t)).toBe('forms:taxTypes.registrationTax')
    expect(taxTypeLabel('registration_tax', t, { registration_tax: 'BPM' })).toBe(
      'forms:taxTypes.registrationTax (BPM)'
    )
    expect(taxTypeLabel('Tolls', t)).toBe('forms:taxTypes.tolls')
    // A stored value this build does not know shows as stored, never blank.
    expect(taxTypeLabel('Income Tax', t)).toBe('Income Tax')
    expect(taxTypeLabel(null, t)).toBe('')
  })

  it("orders the profile's types first, then the rest, once each", () => {
    const options = taxTypeOptions(t, ['circulation_tax', 'inspection', 'circulation_tax', 'bogus'], {
      circulation_tax: 'Kfz-Steuer',
    })
    expect(options.map((o) => o.value).slice(0, 2)).toEqual(['circulation_tax', 'inspection'])
    expect(options[0].label).toBe('forms:taxTypes.circulationTax (Kfz-Steuer)')
    expect(options.map((o) => o.value)).toHaveLength(TAX_TYPE_VALUES.length)
    expect(new Set(options.map((o) => o.value)).size).toBe(TAX_TYPE_VALUES.length)
    expect(taxTypeOptions(t).map((o) => o.value)).toEqual([...TAX_TYPE_VALUES])
  })
})
