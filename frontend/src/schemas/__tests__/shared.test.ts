import { describe, it, expect } from 'vitest'
import { z } from 'zod'
import {
  INVALID_NUMBER,
  MONEY_MAX,
  UNIT_PRICE_MAX,
  makeOptionalCurrencySchema,
  makeCurrencySchema,
  makeOptionalVolumeSchema,
  moneyError,
  moneyTextError,
} from '@/schemas/shared'

const t = ((key: string) => key) as unknown as Parameters<typeof makeCurrencySchema>[0]

// [rev2] MUST test at object level. `z.unknown()` accepts `{amount: undefined}`
// but REJECTS an absent key with invalid_type — a bare safeParse(undefined)
// cannot catch that.
const optObj = z.object({ amount: makeOptionalCurrencySchema(t) })
const reqObj = z.object({ amount: makeCurrencySchema(t) })

describe('optional numeric factory', () => {
  it('accepts an ABSENT key', () => {
    expect(optObj.safeParse({}).success).toBe(true)
  })

  it('accepts an explicitly undefined key', () => {
    expect(optObj.safeParse({ amount: undefined }).success).toBe(true)
  })

  it('accepts a real number and range-checks it with the specific message', () => {
    expect(optObj.safeParse({ amount: 42.5 }).success).toBe(true)

    const neg = optObj.safeParse({ amount: -1 })
    expect(neg.success).toBe(false)
    if (!neg.success) expect(neg.error.issues[0].message).toBe('common:validation.amount.negative')

    const big = z.object({ v: makeOptionalVolumeSchema(t) }).safeParse({ v: 999999 })
    expect(big.success).toBe(false)
    if (!big.success) expect(big.error.issues[0].message).toBe('common:validation.volume.tooLarge')
  })

  it('rejects the invalid sentinel with the translated message', () => {
    const r = optObj.safeParse({ amount: INVALID_NUMBER })
    expect(r.success).toBe(false)
    if (!r.success) expect(r.error.issues[0].message).toBe('common:validation.amount.invalid')
  })

  it('rejects NaN as invalid rather than silently discarding it', () => {
    const r = optObj.safeParse({ amount: NaN })
    expect(r.success).toBe(false)
    if (!r.success) expect(r.error.issues[0].message).toBe('common:validation.amount.invalid')
  })
})

describe('required numeric factory', () => {
  it('rejects an absent key with the required message', () => {
    const r = reqObj.safeParse({})
    expect(r.success).toBe(false)
    if (!r.success) expect(r.error.issues[0].message).toBe('common:validation.amount.required')
  })

  it('rejects the sentinel with the invalid message, distinct from required', () => {
    const r = reqObj.safeParse({ amount: INVALID_NUMBER })
    expect(r.success).toBe(false)
    if (!r.success) expect(r.error.issues[0].message).toBe('common:validation.amount.invalid')
  })

  it('accepts a real number', () => {
    expect(reqObj.safeParse({ amount: 42.5 }).success).toBe(true)
  })

  it('rejects NaN on a REQUIRED field as invalid, not as dropped/empty', () => {
    // Post-Task-8b: NaN can only arrive from a control that failed to parse
    // (never an empty one, since registerDecimal emits undefined for empty),
    // so it now reports invalidKey rather than requiredKey.
    const r = reqObj.safeParse({ amount: NaN })
    expect(r.success).toBe(false)
    if (!r.success) expect(r.error.issues[0].message).toBe('common:validation.amount.invalid')
  })

  it('rejects NaN on an OPTIONAL field as invalid too, not as empty', () => {
    const r = optObj.safeParse({ amount: NaN })
    expect(r.success).toBe(false)
    if (!r.success) expect(r.error.issues[0].message).toBe('common:validation.amount.invalid')
  })
})

// Plan B (money-fits): the API bounds every stored amount at what a
// Numeric(12,2) column holds, whatever the currency. The old 99,999.99 cap
// refused a forint car payment the API takes.
describe('money bounds', () => {
  it('match the API policy in backend app/schemas/_money.py', () => {
    expect(MONEY_MAX).toBe(9_999_999_999.99)
    expect(UNIT_PRICE_MAX).toBe(999_999_999.9999)
  })

  it('an amount takes MONEY_MAX and refuses a cent more, required or not', () => {
    for (const schema of [optObj, reqObj]) {
      expect(schema.safeParse({ amount: MONEY_MAX }).success).toBe(true)
      const over = schema.safeParse({ amount: MONEY_MAX + 0.01 })
      expect(over.success).toBe(false)
      if (!over.success) expect(over.error.issues[0].message).toBe('common:validation.amount.tooLarge')
    }
  })

  it('an amount past the old 99,999.99 cap is accepted', () => {
    // A HUF payment of about $300.
    expect(reqObj.safeParse({ amount: 110_000 }).success).toBe(true)
    expect(optObj.safeParse({ amount: 110_000 }).success).toBe(true)
  })
})

describe('moneyError (for forms that check by hand)', () => {
  it('gives the currency factory message, or undefined when the amount is fine', () => {
    expect(moneyError(t, undefined)).toBeUndefined()
    expect(moneyError(t, 0)).toBeUndefined()
    expect(moneyError(t, MONEY_MAX)).toBeUndefined()
    expect(moneyError(t, MONEY_MAX + 0.01)).toBe('common:validation.amount.tooLarge')
    expect(moneyError(t, -0.01)).toBe('common:validation.amount.negative')
    expect(moneyError(t, NaN)).toBe('common:validation.amount.invalid')
    expect(moneyError(t, INVALID_NUMBER)).toBe('common:validation.amount.invalid')
  })
})

describe('moneyTextError (a typed amount)', () => {
  it('reads the text the way NumberInput does, then applies the same cap', () => {
    expect(moneyTextError(t, '')).toBeUndefined()
    expect(moneyTextError(t, '  ')).toBeUndefined()
    expect(moneyTextError(t, '25000')).toBeUndefined()
    expect(moneyTextError(t, '9999999999.99')).toBeUndefined()
    expect(moneyTextError(t, '10000000000')).toBe('common:validation.amount.tooLarge')
    expect(moneyTextError(t, '-5')).toBe('common:validation.amount.negative')
    expect(moneyTextError(t, 'abc')).toBe('common:validation.amount.invalid')
  })
})
