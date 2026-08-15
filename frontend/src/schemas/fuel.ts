import { z } from 'zod'
import type { TFunction } from 'i18next'
import {
  makeDateSchema,
  makeOptionalOdometerSchema,
  makeOptionalVolumeSchema,
  makeOptionalCurrencySchema,
  makeOptionalPricePerUnitSchema,
  makeOptionalKwhSchema,
  makeOptionalEngineHoursSchema,
  makeNotesSchema,
  makeNumericField,
} from './shared'
import {
  FUEL_TYPE_VALUES,
  PAYMENT_METHOD_VALUES,
  TRIP_TYPE_VALUES,
} from '../constants/fuel'

/**
 * Fuel record schema matching backend Pydantic validators.
 * See: backend/app/schemas/fuel.py
 *
 * Factory, not a constant — see the header of schemas/auth.ts for why.
 */

export const PRICE_BASIS_VALUES = ['per_volume', 'per_weight', 'per_kwh', 'per_tank'] as const

// Drop empty strings before validating an optional enum — HTML <select>
// elements without a chosen value submit "" by default, and zod's enum
// validator would reject that. Coerce empty -> undefined first.
const optionalEnum = <T extends readonly [string, ...string[]]>(values: T) =>
  z
    .union([z.enum(values), z.literal(''), z.undefined()])
    .transform((v) => (v === '' || v === undefined ? undefined : v))

export const makeFuelRecordSchema = (t: TFunction) =>
  z.object({
    date: makeDateSchema(t),
    filled_at: z.string().optional(),
    odometer_km: makeOptionalOdometerSchema(t),
    engine_hours: makeOptionalEngineHoursSchema(t),
    liters: makeOptionalVolumeSchema(t),
    propane_liters: makeOptionalVolumeSchema(t),
    kwh: makeOptionalKwhSchema(t),
    // Same 0–100% pattern as def_fill_level (NumberInput / registerDecimal).
    soc_start_pct: makeNumericField(t, {
      min: 0,
      max: 100,
      negativeKey: 'common:validation.def.fillLevelNegative',
      tooLargeKey: 'common:validation.def.fillLevelTooLarge',
      invalidKey: 'common:validation.def.fillLevelInvalid',
    }),
    soc_end_pct: makeNumericField(t, {
      min: 0,
      max: 100,
      negativeKey: 'common:validation.def.fillLevelNegative',
      tooLargeKey: 'common:validation.def.fillLevelTooLarge',
      invalidKey: 'common:validation.def.fillLevelInvalid',
    }),
    charge_level: optionalEnum(['L1', 'L2', 'DCFC'] as const),
    charge_location: optionalEnum(['home', 'public'] as const),
    battery_soh_pct: makeNumericField(t, {
      min: 0,
      max: 100,
      negativeKey: 'common:validation.def.fillLevelNegative',
      tooLargeKey: 'common:validation.def.fillLevelTooLarge',
      invalidKey: 'common:validation.def.fillLevelInvalid',
    }),
    cost: makeOptionalCurrencySchema(t),
    rebate: makeOptionalCurrencySchema(t),
    price_per_unit: makeOptionalPricePerUnitSchema(t),
    price_basis: z.enum(PRICE_BASIS_VALUES).optional(),
    fuel_type: z.string().max(50, t('common:validation.fuel.fuelTypeTooLong')).optional(),
    fuel_type_used: optionalEnum(FUEL_TYPE_VALUES),
    is_full_tank: z.boolean(),
    missed_fillup: z.boolean(),
    is_hauling: z.boolean(),
    notes: makeNotesSchema(t).optional(),
    // Task 8 moved this onto NumberInput/registerDecimal, which can hand the
    // schema INVALID_NUMBER for unparseable text — the old `.or(z.nan())`
    // shape only recognized number/NaN and leaked zod's raw union error.
    // Same percentage concept (and same keys) as DEFRecordForm's fill_level.
    def_fill_level: makeNumericField(t, {
      min: 0,
      max: 100,
      negativeKey: 'common:validation.def.fillLevelNegative',
      tooLargeKey: 'common:validation.def.fillLevelTooLarge',
      invalidKey: 'common:validation.def.fillLevelInvalid',
    }),
    // Issue #69 — extended fuel tracking
    station_address_book_id: z
      .number()
      .int()
      .positive()
      .or(z.nan())
      .transform((val) => (isNaN(val) ? undefined : val))
      .optional(),
    station_name_freetext: z.string().max(150).optional(),
    one_time_visit: z.boolean().optional(),
    driver_user_id: z
      .number()
      .int()
      .positive()
      .or(z.nan())
      .transform((val) => (isNaN(val) ? undefined : val))
      .optional(),
    driver_name_freetext: z.string().max(100).optional(),
    payment_method: optionalEnum(PAYMENT_METHOD_VALUES),
    trip_type: optionalEnum(TRIP_TYPE_VALUES),
    outside_temp_c: z
      .number()
      .min(-60)
      .max(70)
      .or(z.nan())
      .transform((val) => (isNaN(val) ? undefined : val))
      .optional(),
    // Task 8 moved both onto NumberInput/registerDecimal — same reasoning as
    // def_fill_level above. Neither had a custom message before (bare
    // `.min(0)`, zod's default), so both reuse one new "obc" key family.
    obc_l_per_100km: makeNumericField(t, {
      min: 0,
      max: Infinity,
      negativeKey: 'common:validation.fuel.obcNegative',
      tooLargeKey: 'common:validation.fuel.obcTooLarge',
      invalidKey: 'common:validation.fuel.obcInvalid',
    }),
    obc_avg_speed_kmh: makeNumericField(t, {
      min: 0,
      max: Infinity,
      negativeKey: 'common:validation.fuel.obcNegative',
      tooLargeKey: 'common:validation.fuel.obcTooLarge',
      invalidKey: 'common:validation.fuel.obcInvalid',
    }),
    // OBC trip duration accepts ``HH:MM``, ``HH:MM:SS``, or an integer
    // string of seconds. Backend pre-validator in app/schemas/fuel.py
    // parses to canonical seconds; we don't coerce on the frontend so
    // the user's literal input flows through unchanged. Surfaced by
    // issue #69 — many onboard computers display duration as HH:MM.
    obc_trip_duration_s: z
      .string()
      .regex(
        /^(\s*|\d+|\d{1,3}:\d{2}(?::\d{2})?)$/,
        t('common:validation.fuel.obcTripDurationFormat')
      )
      .optional()
      .or(z.literal('')),
  })

// Export both input and output types for Zod v4 zodResolver compatibility
// z.input = what the form supplies (unknown for coerce fields)
// z.output = coerced result after validation (numbers)
export type FuelRecordInput = z.input<ReturnType<typeof makeFuelRecordSchema>>
export type FuelRecordFormData = z.output<ReturnType<typeof makeFuelRecordSchema>>
