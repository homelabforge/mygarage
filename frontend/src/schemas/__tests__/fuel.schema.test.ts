import { describe, it, expect } from 'vitest'
import type { TFunction } from 'i18next'
import { makeFuelRecordSchema } from '../fuel'
import { INVALID_NUMBER, MONEY_MAX, UNIT_PRICE_MAX } from '../shared'
import { IMPERIAL_UNITS, METRIC_UNITS } from '@/__tests__/factories'

// Same shape as the global react-i18next mock in src/__tests__/setup.ts:
// messages come back as their i18n key, which is all these tests need.
//
// Named fuel.schema.test.ts (not fuel.test.ts) — that file already exists
// and exercises a disconnected local mock schema, not the real
// makeFuelRecordSchema. This file tests the actual production schema.
const t = ((key: string) => key) as unknown as TFunction

const fuelRecordSchema = makeFuelRecordSchema(t, METRIC_UNITS)

const REQUIRED = {
  date: '2026-04-30',
  is_full_tank: true,
  missed_fillup: false,
  is_hauling: false,
  // Explicit undefined covers RHF-registered-but-empty selects. Absent keys
  // are also accepted (optionalEnum is .optional()) — charge_* fields are
  // unregistered when showKwh is false.
  fuel_type_used: undefined,
  payment_method: undefined,
  trip_type: undefined,
}

describe('Fuel Record Schema — def_fill_level / obc fields (Task 8)', () => {
  // Task 8 moved def_fill_level, obc_l_per_100km, and obc_avg_speed_kmh onto
  // NumberInput/registerDecimal, which can hand this schema the
  // INVALID_NUMBER sentinel for unparseable text — the old `.or(z.nan())`
  // shape only recognized number/NaN and leaked zod's raw
  // "Invalid input: expected number, received symbol" instead of a
  // translated message.
  it('rejects the INVALID_NUMBER sentinel on def_fill_level/obc fields with translated messages, not a raw zod union error', () => {
    const result = fuelRecordSchema.safeParse({
      ...REQUIRED,
      def_fill_level: INVALID_NUMBER,
      obc_l_per_100km: INVALID_NUMBER,
      obc_avg_speed_kmh: INVALID_NUMBER,
    })
    expect(result.success).toBe(false)
    if (!result.success) {
      const messages = result.error.issues.map(i => i.message)
      expect(messages).toContain('common:validation.def.fillLevelInvalid')
      expect(messages).toContain('common:validation.fuel.obcInvalid')
      for (const m of messages) {
        expect(m).not.toMatch(/received symbol|expected number/i)
      }
    }
  })

  it('rejects NaN on these fields as invalid rather than silently discarding it (Task 8b)', () => {
    const result = fuelRecordSchema.safeParse({
      ...REQUIRED,
      def_fill_level: NaN,
    })
    expect(result.success).toBe(false)
  })

  it('still accepts valid values and preserves the def_fill_level 0-100 bound', () => {
    const ok = fuelRecordSchema.safeParse({ ...REQUIRED, def_fill_level: 75, obc_l_per_100km: 8.2, obc_avg_speed_kmh: 62 })
    expect(ok.success).toBe(true)

    const tooHigh = fuelRecordSchema.safeParse({ ...REQUIRED, def_fill_level: 101 })
    expect(tooHigh.success).toBe(false)

    const negativeObc = fuelRecordSchema.safeParse({ ...REQUIRED, obc_l_per_100km: -1 })
    expect(negativeObc.success).toBe(false)
  })
})

// money-fits (audit §6, Fable F-B4): the API caps price_per_unit in $/L or
// $/kg, and the form's price_basis select decides which unit the typed number
// is per. So the cap is an object-level check that reads the basis off the
// same parse, not a number baked into the field.
describe('Fuel Record Schema: the unit-price cap follows the price basis', () => {
  const imperial = makeFuelRecordSchema(t, IMPERIAL_UNITS)
  const priceMessages = (
    schema: ReturnType<typeof makeFuelRecordSchema>,
    input: Record<string, unknown>,
  ): string[] => {
    const result = schema.safeParse({ ...REQUIRED, ...input })
    return result.success ? [] : result.error.issues.map((issue) => `${issue.path.join('.')}: ${issue.message}`)
  }
  const TOO_LARGE = 'price_per_unit: common:validation.price.tooLarge'

  it('a litre price takes UNIT_PRICE_MAX and refuses a hundredth of a cent more', () => {
    expect(priceMessages(fuelRecordSchema, { price_per_unit: UNIT_PRICE_MAX, price_basis: 'per_volume' })).toEqual([])
    expect(
      priceMessages(fuelRecordSchema, { price_per_unit: UNIT_PRICE_MAX + 0.0001, price_basis: 'per_volume' }),
    ).toEqual([TOO_LARGE])
  })

  it('a per-pound price is capped where it converts past the API max', () => {
    // 453,592,369 $/lb is about 999,999,998 $/kg; 453,592,370 is just over 1e9.
    expect(priceMessages(imperial, { price_per_unit: 453_592_369, price_basis: 'per_weight' })).toEqual([])
    expect(priceMessages(imperial, { price_per_unit: 453_592_370, price_basis: 'per_weight' })).toEqual([TOO_LARGE])
  })

  it('a per-gallon price over UNIT_PRICE_MAX passes while it converts under it', () => {
    expect(priceMessages(imperial, { price_per_unit: 3_000_000_000, price_basis: 'per_volume' })).toEqual([])
    expect(priceMessages(imperial, { price_per_unit: 3_785_411_785, price_basis: 'per_volume' })).toEqual([TOO_LARGE])
  })

  it('the same number passes per gallon and fails per pound: the basis select decides', () => {
    expect(priceMessages(imperial, { price_per_unit: 500_000_000, price_basis: 'per_volume' })).toEqual([])
    expect(priceMessages(imperial, { price_per_unit: 500_000_000, price_basis: 'per_weight' })).toEqual([TOO_LARGE])
  })

  it('per_kwh and per_tank convert nothing', () => {
    for (const basis of ['per_kwh', 'per_tank']) {
      expect(priceMessages(imperial, { price_per_unit: UNIT_PRICE_MAX, price_basis: basis })).toEqual([])
      expect(priceMessages(imperial, { price_per_unit: UNIT_PRICE_MAX + 0.0001, price_basis: basis })).toEqual([
        TOO_LARGE,
      ])
    }
  })

  it('a negative or unreadable price keeps its own message and gets no second one', () => {
    expect(priceMessages(imperial, { price_per_unit: -1, price_basis: 'per_weight' })).toEqual([
      'price_per_unit: common:validation.price.negative',
    ])
    expect(priceMessages(imperial, { price_per_unit: INVALID_NUMBER, price_basis: 'per_weight' })).toEqual([
      'price_per_unit: common:validation.price.invalid',
    ])
  })

  it('cost and rebate take MONEY_MAX and refuse a cent more', () => {
    expect(priceMessages(fuelRecordSchema, { cost: MONEY_MAX, rebate: MONEY_MAX })).toEqual([])
    expect(priceMessages(fuelRecordSchema, { cost: MONEY_MAX + 0.01, rebate: MONEY_MAX + 0.01 })).toEqual([
      'cost: common:validation.amount.tooLarge',
      'rebate: common:validation.amount.tooLarge',
    ])
  })
})
