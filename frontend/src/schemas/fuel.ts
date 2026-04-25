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

/**
 * Fuel record schema matching backend Pydantic validators.
 * See: backend/app/schemas/fuel.py
 */

export const PRICE_BASIS_VALUES = ['per_volume', 'per_weight', 'per_kwh', 'per_tank'] as const

export const fuelRecordSchema = z.object({
  date: dateSchema,
  odometer_km: optionalOdometerSchema,
  liters: optionalVolumeSchema,
  propane_liters: optionalVolumeSchema,
  kwh: optionalKwhSchema,
  cost: optionalCurrencySchema,
  price_per_unit: optionalPricePerUnitSchema,
  price_basis: z.enum(PRICE_BASIS_VALUES).optional(),
  fuel_type: z.string().max(50, 'Fuel type too long').optional(),
  is_full_tank: z.boolean(),
  missed_fillup: z.boolean(),
  is_hauling: z.boolean(),
  notes: notesSchema.optional(),
  def_fill_level: z.number().min(0).max(100).or(z.nan()).transform(val => isNaN(val) ? undefined : val).optional(),
})

// Export both input and output types for Zod v4 zodResolver compatibility
// z.input = what the form supplies (unknown for coerce fields)
// z.output = coerced result after validation (numbers)
export type FuelRecordInput = z.input<typeof fuelRecordSchema>
export type FuelRecordFormData = z.output<typeof fuelRecordSchema>
