import { describe, it, expect } from 'vitest'
import type { TFunction } from 'i18next'
import { makeFuelRecordSchema } from '../fuel'
import { INVALID_NUMBER } from '../shared'

// Same shape as the global react-i18next mock in src/__tests__/setup.ts:
// messages come back as their i18n key, which is all these tests need.
//
// Named fuel.schema.test.ts (not fuel.test.ts) — that file already exists
// and exercises a disconnected local mock schema, not the real
// makeFuelRecordSchema. This file tests the actual production schema.
const t = ((key: string) => key) as unknown as TFunction

const fuelRecordSchema = makeFuelRecordSchema(t)

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
