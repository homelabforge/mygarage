import { z } from 'zod'
import {
  dateSchema,
  optionalOdometerSchema,
  optionalVolumeSchema,
  optionalCurrencySchema,
  optionalPricePerUnitSchema,
  optionalKwhSchema,
  notesSchema,
} from './shared'
import {
  FUEL_TYPE_VALUES,
  PAYMENT_METHOD_VALUES,
  TRIP_TYPE_VALUES,
} from '../constants/fuel'

/**
 * Fuel record schema matching backend Pydantic validators.
 * See: backend/app/schemas/fuel.py
 */

export const PRICE_BASIS_VALUES = ['per_volume', 'per_weight', 'per_kwh', 'per_tank'] as const

// Drop empty strings before validating an optional enum — HTML <select>
// elements without a chosen value submit "" by default, and zod's enum
// validator would reject that. Coerce empty -> undefined first.
const optionalEnum = <T extends readonly [string, ...string[]]>(values: T) =>
  z
    .union([z.enum(values), z.literal(''), z.undefined()])
    .transform((v) => (v === '' || v === undefined ? undefined : v))

export const fuelRecordSchema = z.object({
  date: dateSchema,
  filled_at: z.string().optional(),
  odometer_km: optionalOdometerSchema,
  liters: optionalVolumeSchema,
  propane_liters: optionalVolumeSchema,
  kwh: optionalKwhSchema,
  cost: optionalCurrencySchema,
  rebate: optionalCurrencySchema,
  price_per_unit: optionalPricePerUnitSchema,
  price_basis: z.enum(PRICE_BASIS_VALUES).optional(),
  fuel_type: z.string().max(50, 'Fuel type too long').optional(),
  fuel_type_used: optionalEnum(FUEL_TYPE_VALUES),
  is_full_tank: z.boolean(),
  missed_fillup: z.boolean(),
  is_hauling: z.boolean(),
  notes: notesSchema.optional(),
  def_fill_level: z
    .number()
    .min(0)
    .max(100)
    .or(z.nan())
    .transform((val) => (isNaN(val) ? undefined : val))
    .optional(),
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
  obc_l_per_100km: z
    .number()
    .min(0)
    .or(z.nan())
    .transform((val) => (isNaN(val) ? undefined : val))
    .optional(),
  obc_avg_speed_kmh: z
    .number()
    .min(0)
    .or(z.nan())
    .transform((val) => (isNaN(val) ? undefined : val))
    .optional(),
  // OBC trip duration accepts ``HH:MM``, ``HH:MM:SS``, or an integer
  // string of seconds. Backend pre-validator in app/schemas/fuel.py
  // parses to canonical seconds; we don't coerce on the frontend so
  // the user's literal input flows through unchanged. Surfaced by
  // issue #69 — many onboard computers display duration as HH:MM.
  obc_trip_duration_s: z
    .string()
    .regex(
      /^(\s*|\d+|\d{1,3}:\d{2}(?::\d{2})?)$/,
      "Use seconds (e.g. 8100), HH:MM (e.g. 2:15), or HH:MM:SS"
    )
    .optional()
    .or(z.literal('')),
})

// Export both input and output types for Zod v4 zodResolver compatibility
// z.input = what the form supplies (unknown for coerce fields)
// z.output = coerced result after validation (numbers)
export type FuelRecordInput = z.input<typeof fuelRecordSchema>
export type FuelRecordFormData = z.output<typeof fuelRecordSchema>
