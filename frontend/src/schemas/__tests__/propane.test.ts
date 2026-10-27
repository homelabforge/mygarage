import { describe, it, expect } from 'vitest'
import { makePropaneRecordSchema } from '../propane'
import { INVALID_NUMBER, MONEY_MAX, UNIT_PRICE_MAX } from '../shared'
import { IMPERIAL_UNITS, METRIC_UNITS } from '@/__tests__/factories'

const t = ((key: string) => key) as unknown as Parameters<typeof makePropaneRecordSchema>[0]
const propaneRecordSchema = makePropaneRecordSchema(t, METRIC_UNITS)

describe('Propane Record Schema', () => {
  const validPropane = {
    date: '2024-09-15',
  }

  it('validates valid propane record with required fields only', () => {
    const result = propaneRecordSchema.safeParse(validPropane)
    expect(result.success).toBe(true)
  })

  it('validates propane record with all optional fields', () => {
    const result = propaneRecordSchema.safeParse({
      ...validPropane,
      propane_liters: 7.5,
      tank_size_kg: 30,
      tank_quantity: 2,
      price_per_unit: 4.50,
      cost: 33.75,
      vendor: 'U-Haul',
      notes: 'Refilled both 30lb tanks',
    })
    expect(result.success).toBe(true)
  })

  it('requires date', () => {
    const result = propaneRecordSchema.safeParse({})
    expect(result.success).toBe(false)
  })

  it('rejects non-positive propane_liters', () => {
    const result = propaneRecordSchema.safeParse({
      ...validPropane,
      propane_liters: 0,
    })
    expect(result.success).toBe(false)
  })

  it('rejects non-integer tank_quantity', () => {
    const result = propaneRecordSchema.safeParse({
      ...validPropane,
      tank_quantity: 1.5,
    })
    expect(result.success).toBe(false)
  })

  it('rejects negative cost', () => {
    const result = propaneRecordSchema.safeParse({
      ...validPropane,
      cost: -10,
    })
    expect(result.success).toBe(false)
  })

  // tank_size_kg stays on the old .or(z.nan()) shape (its <Select> stays on
  // valueAsNumber and never produces INVALID_NUMBER), so NaN still transforms
  // to undefined there. propane_liters/cost now route through the shared
  // makeNumericField (post-Task-8b), which rejects NaN as invalid rather
  // than treating it as empty — see shared.test.ts.
  it('transforms NaN tank_size_kg to undefined (bespoke Select-backed field, unaffected by Task 8/8b)', () => {
    const result = propaneRecordSchema.safeParse({
      ...validPropane,
      tank_size_kg: NaN,
    })
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.tank_size_kg).toBeUndefined()
    }
  })

  it('rejects NaN propane_liters/cost as invalid rather than silently discarding them', () => {
    const result = propaneRecordSchema.safeParse({
      ...validPropane,
      propane_liters: NaN,
      cost: NaN,
    })
    expect(result.success).toBe(false)
  })

  it('rejects vendor over 100 characters', () => {
    const result = propaneRecordSchema.safeParse({
      ...validPropane,
      vendor: 'A'.repeat(101),
    })
    expect(result.success).toBe(false)
  })

  // Regression for the CRITICAL finding: the pre-refactor `.or(z.nan())`
  // shape these fields used to have couldn't recognize INVALID_NUMBER (the
  // sentinel registerDecimal emits for unparseable text) and leaked zod's
  // raw "Invalid input: expected number, received symbol" instead of a
  // translated message. Assert each converted field now reports one.
  it('rejects the INVALID_NUMBER sentinel with translated messages, not a raw zod union error', () => {
    const result = propaneRecordSchema.safeParse({
      ...validPropane,
      propane_liters: INVALID_NUMBER,
      tank_quantity: INVALID_NUMBER,
      price_per_unit: INVALID_NUMBER,
      cost: INVALID_NUMBER,
    })
    expect(result.success).toBe(false)
    if (!result.success) {
      const messages = result.error.issues.map(i => i.message)
      expect(messages).toContain('common:validation.volume.invalid')
      expect(messages).toContain('common:validation.tankQuantity.invalid')
      expect(messages).toContain('common:validation.price.invalid')
      expect(messages).toContain('common:validation.amount.invalid')
      for (const m of messages) {
        expect(m).not.toMatch(/received symbol|expected number/i)
      }
    }
  })
})

describe('Propane Record Schema: the tank pair', () => {
  // The API refuses a tank size without a count, or a count without a size.
  const base = { date: '2024-09-15', propane_liters: 7.5 }
  const issuesAt = (input: Record<string, unknown>) => {
    const result = propaneRecordSchema.safeParse({ ...base, ...input })
    return result.success ? [] : result.error.issues.map((issue) => issue.path.join('.'))
  }

  it('a size without a count flags the count', () => {
    expect(issuesAt({ tank_size_kg: 9.07 })).toEqual(['tank_quantity'])
  })

  it('a count without a size flags the size', () => {
    expect(issuesAt({ tank_quantity: 2 })).toEqual(['tank_size_kg'])
  })

  it('an unreadable count with no size gets the count error only, not the pair one too', () => {
    // A failed field parse leaves the raw INVALID_NUMBER sentinel in place,
    // which is not a count.
    expect(issuesAt({ tank_size_kg: NaN, tank_quantity: INVALID_NUMBER })).toEqual(['tank_quantity'])
  })

  it('both or neither is fine', () => {
    expect(issuesAt({ tank_size_kg: 9.07, tank_quantity: 2 })).toEqual([])
    expect(issuesAt({})).toEqual([])
  })
})

// money-fits: the cost takes the API's MONEY_MAX, and the price is capped
// where the API caps it, in $/L. The form always posts per_volume, so the
// typed value converts through the user's volume unit.
describe('Propane Record Schema: money bounds', () => {
  const base = { date: '2024-09-15' }
  const messagesFor = (schema: ReturnType<typeof makePropaneRecordSchema>, input: Record<string, unknown>) => {
    const result = schema.safeParse({ ...base, ...input })
    return result.success ? [] : result.error.issues.map((issue) => `${issue.path.join('.')}: ${issue.message}`)
  }

  it('the cost takes MONEY_MAX and refuses a cent more', () => {
    expect(messagesFor(propaneRecordSchema, { cost: MONEY_MAX })).toEqual([])
    expect(messagesFor(propaneRecordSchema, { cost: MONEY_MAX + 0.01 })).toEqual([
      'cost: common:validation.amount.tooLarge',
    ])
  })

  it('a litre price takes UNIT_PRICE_MAX and refuses a hundredth of a cent more', () => {
    expect(messagesFor(propaneRecordSchema, { price_per_unit: UNIT_PRICE_MAX })).toEqual([])
    expect(messagesFor(propaneRecordSchema, { price_per_unit: UNIT_PRICE_MAX + 0.0001 })).toEqual([
      'price_per_unit: common:validation.price.tooLarge',
    ])
  })

  it('a gallon price is capped at what it converts to per litre, not at the typed number', () => {
    const gallons = makePropaneRecordSchema(t, IMPERIAL_UNITS)
    // 3,000,000,000 $/gal is about 792,516,157 $/L: fine.
    expect(messagesFor(gallons, { price_per_unit: 3_000_000_000 })).toEqual([])
    // 3,785,411,785 $/gal is 1,000,000,000.26 $/L: over.
    expect(messagesFor(gallons, { price_per_unit: 3_785_411_785 })).toEqual([
      'price_per_unit: common:validation.price.tooLarge',
    ])
  })

  it('a negative or unreadable price keeps its own message and gets no second one', () => {
    expect(messagesFor(propaneRecordSchema, { price_per_unit: -1 })).toEqual([
      'price_per_unit: common:validation.price.negative',
    ])
    expect(messagesFor(propaneRecordSchema, { price_per_unit: INVALID_NUMBER })).toEqual([
      'price_per_unit: common:validation.price.invalid',
    ])
  })
})
